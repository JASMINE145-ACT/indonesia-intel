"""Tick: retest PDF-unlocked + flaky + L2-needed prefer sources."""
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

THEME = "Indonesia China investment OR nickel OR EV OR battery"
OUT = ROOT / "evidence" / "prefer-l1-llm-capability-tick2.json"
BASE = ROOT / "data" / "_e2e_probe" / "prefer_tick2"

# Previously failed or flaky / newly PDF-unlocked
PROBE = [
    "cninfo",
    "szse",
    "hkexnews",
    "sse",
    "bkpm",
    "idx",
    "kadin",
    "mofcom_id_embassy",
    "reuters",
    "worldbank_id",
    "caixin_global",
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


async def search_site(provider, domain: str):
    q = f"site:{domain} {THEME}"
    hits = await provider.search(q)
    return q, [h for h in hits if _domain_match(h.url, domain)][:3]


def main() -> int:
    if not settings.exa_api_key:
        print("no exa key", flush=True)
        return 1
    reg = load_merged()
    provider = get_provider("exa", exa_api_key=settings.exa_api_key)
    SessionLocal = _wire()
    blob = LocalBlobStore(BASE / "blobs")
    rows_out = []

    with SessionLocal() as session:
        for r in session.scalars(select(ReviewCandidate)):
            session.delete(r)
        session.commit()

        for sid in PROBE:
            src = reg.get(sid)
            if not src or not src.enabled:
                continue
            print(f"== {sid}", flush=True)
            try:
                q, hits = asyncio.run(search_site(provider, src.domain))
            except Exception as exc:  # noqa: BLE001
                rows_out.append(
                    {
                        "id": sid,
                        "pipeline": "blocked_at_search",
                        "error": f"{type(exc).__name__}: {exc}"[:180],
                    }
                )
                print(f"   search_fail {type(exc).__name__}", flush=True)
                continue
            if not hits:
                rows_out.append({"id": sid, "pipeline": "no_hits", "hits": 0})
                print("   no_hits", flush=True)
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
            # enable L2 for idx / mofcom / kompas-style
            fetch = fetch_discovered_candidates(
                session, blob, limit=len(hits), enable_l2=True
            )
            usable = []
            for r in session.scalars(
                select(ReviewCandidate).where(ReviewCandidate.run_id == rid)
            ):
                if r.status != "pending_review":
                    continue
                blob_ok = bool(r.object_key) and (blob.root / r.object_key).is_file()
                html = (blob.root / r.object_key).read_bytes()[:20000] if blob_ok else b""
                v = assess_extracted_page(title=r.title, text=r.extracted_text, html=html)
                ok = (
                    blob_ok
                    and len(r.extracted_text or "") >= 80
                    and bool((r.title or "").strip())
                    and v.ok
                )
                if ok:
                    usable.append(
                        {
                            "title": (r.title or "")[:80],
                            "text_len": len(r.extracted_text or ""),
                            "url": r.canonical_url,
                            "kind": "pdf" if (r.object_key or "").endswith(".pdf") else "html",
                        }
                    )
            pipe = "ok" if usable else "fetch_fail"
            rows_out.append(
                {
                    "id": sid,
                    "hits": len(hits),
                    "fetch": {k: fetch[k] for k in ("fetched", "failed", "l2_used")},
                    "usable_n": len(usable),
                    "usable_sample": usable[:2],
                    "pipeline": pipe,
                }
            )
            print(f"   {pipe} usable={len(usable)} l2={fetch.get('l2_used')}", flush=True)

    ok_ids = [r["id"] for r in rows_out if r.get("pipeline") == "ok"]
    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "ok_ids": ok_ids,
        "rows": rows_out,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok_ids": ok_ids}, ensure_ascii=False, indent=2))
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
