"""Prefer-pool × LLM search (Exa site:) × L1 fetch → local store capability matrix.

Does NOT print API keys. Uses Exa + L1 only (no Scrapling L2).
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import Base
from app.models import ReviewCandidate
from dedup.url import normalize_url, url_hash
from fetch.content_validity import assess_extracted_page
from jobs.fetch_candidates import fetch_discovered_candidates
from providers.factory import get_provider
from sources.store import load_merged
from storage.blob import LocalBlobStore

OUT = ROOT / "evidence" / "prefer-l1-llm-capability.json"
BASE = ROOT / "data" / "_e2e_probe" / "prefer_l1_llm"
# Keyword theme for China→Indonesia intel
THEME = "Indonesia China investment OR nickel OR EV OR factory"


# Priority A + a few B media that fetch_mode=search (LLM-native)
PROBE_IDS = [
    # CN A
    "cninfo",
    "sse",
    "szse",
    "hkexnews",
    "mofcom_id_embassy",
    # ID A
    "bkpm",
    "kemenperin",
    "esdm",
    "ojk",
    "idx",
    "kadin",
    "imip",
    "antara",
    "kompas",
    # INT A
    "reuters",
    "worldbank_id",
    "imf_id",
    "iea_id",
    "dealstreetasia",
    # B useful media
    "kontan_en",
    "yicai_global",
    "caixin_global",
    "krasia",
]


def _wire():
    BASE.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{(BASE / 'e2e.db').as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _domain_match(url: str, domain: str) -> bool:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    d = domain.lower().removeprefix("www.")
    return host == d or host.endswith("." + d)


async def search_site(provider, domain: str, query: str, *, max_hits: int = 5):
    q = f"site:{domain} {query}"
    hits = await provider.search(q)
    # keep only matching domain
    filtered = [h for h in hits if _domain_match(h.url, domain)]
    return q, filtered[:max_hits]


def main() -> int:
    if not settings.exa_api_key:
        print("FAIL: EXA_API_KEY not loaded", flush=True)
        return 1

    reg = load_merged()
    provider = get_provider("exa", exa_api_key=settings.exa_api_key)
    SessionLocal = _wire()
    blob = LocalBlobStore(BASE / "blobs")
    rows_out = []

    with SessionLocal() as session:
        # clear
        for r in session.scalars(select(ReviewCandidate)):
            session.delete(r)
        session.commit()

        for sid in PROBE_IDS:
            src = reg.get(sid)
            if src is None or not src.enabled:
                rows_out.append({"id": sid, "status": "missing_or_disabled"})
                continue
            domain = src.domain
            print(f"== {sid} site:{domain}", flush=True)
            try:
                q, hits = asyncio.run(search_site(provider, domain, THEME, max_hits=4))
            except Exception as exc:  # noqa: BLE001
                rows_out.append(
                    {
                        "id": sid,
                        "domain": domain,
                        "priority": src.priority,
                        "fetch_mode": src.fetch_mode,
                        "search_ok": False,
                        "search_error": f"{type(exc).__name__}: {exc}"[:200],
                        "pipeline": "blocked_at_search",
                    }
                )
                continue

            if not hits:
                rows_out.append(
                    {
                        "id": sid,
                        "domain": domain,
                        "priority": src.priority,
                        "fetch_mode": src.fetch_mode,
                        "search_ok": True,
                        "hits": 0,
                        "pipeline": "no_hits_for_theme",
                        "query": q,
                    }
                )
                continue

            rid = uuid.uuid4().hex[:12]
            for h in hits:
                session.add(
                    ReviewCandidate(
                        run_id=rid,
                        provider="exa",
                        query=q,
                        original_url=h.url,
                        canonical_url=normalize_url(h.url),
                        url_hash=url_hash(h.url),
                        title=h.title or "",
                        snippet=h.snippet or "",
                        source_domain=h.source_domain,
                        source_id=sid,
                        status="discovered",
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()

            fetch = fetch_discovered_candidates(
                session,
                blob,
                limit=len(hits),
                enable_l2=False,  # L1 only as asked
            )

            usable = []
            failed = []
            for r in session.scalars(
                select(ReviewCandidate).where(ReviewCandidate.run_id == rid)
            ):
                if r.status == "pending_review":
                    blob_ok = bool(r.object_key) and (blob.root / r.object_key).is_file()
                    html = (
                        (blob.root / r.object_key).read_bytes()[:20000] if blob_ok else b""
                    )
                    v = assess_extracted_page(
                        title=r.title, text=r.extracted_text, html=html
                    )
                    ok = (
                        blob_ok
                        and len(r.extracted_text or "") >= 80
                        and bool((r.title or "").strip())
                        and v.ok
                    )
                    item = {
                        "title": (r.title or "")[:100],
                        "url": r.canonical_url,
                        "text_len": len(r.extracted_text or ""),
                        "usable": ok,
                    }
                    if ok:
                        usable.append(item)
                    else:
                        failed.append({**item, "reason": v.error_type or "weak"})
                else:
                    failed.append(
                        {
                            "title": (r.title or "")[:80],
                            "url": r.canonical_url,
                            "status": r.status,
                            "reason": (r.snippet or "")[:120],
                        }
                    )

            pipeline = (
                "ok_search_l1_local"
                if usable
                else ("search_ok_l1_fetch_fail" if hits else "no_hits")
            )
            rows_out.append(
                {
                    "id": sid,
                    "domain": domain,
                    "priority": src.priority,
                    "region": src.region,
                    "fetch_mode": src.fetch_mode,
                    "search_ok": True,
                    "hits": len(hits),
                    "query": q,
                    "fetch": {
                        k: fetch[k] for k in ("fetched", "failed", "total", "l2_used")
                    },
                    "usable_n": len(usable),
                    "usable_sample": usable[:2],
                    "fail_sample": failed[:2],
                    "pipeline": pipeline,
                }
            )
            print(
                f"   hits={len(hits)} usable={len(usable)} pipeline={pipeline}",
                flush=True,
            )

    ok_ids = [r["id"] for r in rows_out if r.get("pipeline") == "ok_search_l1_local"]
    search_only = [
        r["id"] for r in rows_out if r.get("pipeline") == "search_ok_l1_fetch_fail"
    ]
    no_hits = [r["id"] for r in rows_out if r.get("pipeline") == "no_hits_for_theme"]
    blocked = [
        r["id"]
        for r in rows_out
        if r.get("pipeline") in ("blocked_at_search",) or r.get("status")
    ]

    # Antara RSS native path (no LLM) — still L1 fixed pool gold path
    antara_rss_note = (
        "antara also works without LLM via RSS→L1 (proven e2e); "
        "site: search above is LLM-assisted discovery alternative"
    )

    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "definition": (
            "LLM加持 = Exa site:{prefer_domain} + keyword theme; "
            "下载 = L1 httpx/Trafilatura only → SQLite+blob"
        ),
        "theme": THEME,
        "provider": "exa",
        "l2_used": False,
        "verdict": {
            "can_search_and_store_local_now": ok_ids,
            "search_hits_but_l1_cannot_download": search_only,
            "llm_search_no_relevant_hits": no_hits,
            "other": blocked,
        },
        "antara_rss_note": antara_rss_note,
        "rows": rows_out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["verdict"], ensure_ascii=False, indent=2))
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
