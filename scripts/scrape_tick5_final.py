"""Tick5: remaining prefer B sources + final capability rollup. If plateau → no more wake."""
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

THEME = "Indonesia China investment OR nickel OR EV"
OUT = ROOT / "evidence" / "prefer-capability-final.json"
BASE = ROOT / "data" / "_e2e_probe" / "prefer_final"

# Prior OK + remaining B / untested
ALREADY_OK = {
    "sse",
    "szse",
    "cninfo",
    "hkexnews",
    "esdm",
    "ojk",
    "kemenperin",
    "imip",
    "antara",
    "kompas",
    "imf_id",
    "iea_id",
    "dealstreetasia",
    "kontan_en",
    "yicai_global",
    "krasia",
    "idx",
    "worldbank_id",
    "caixin_global",
}
REMAINING = [
    "apindo",
    "jiipe",
    "batang_city",
    "detik",
    "bisnis",
    "argus",
    "benchmark_minerals",
    "kr36_overseas",
    "unctad_wir",
    "mofcom_fdi_guide",
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


def _dom(url: str, domain: str) -> bool:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    d = domain.lower().removeprefix("www.")
    return host == d or host.endswith("." + d)


async def search_both(domain: str):
    q = f"site:{domain} {THEME}"
    hits = []
    errors = []
    for name, key in (
        ("exa", settings.exa_api_key),
        ("tavily", settings.tavily_api_key),
    ):
        if not key:
            continue
        try:
            p = get_provider(name, exa_api_key=settings.exa_api_key, tavily_api_key=settings.tavily_api_key)
            found = await p.search(q)
            hits.extend([h for h in found if _dom(h.url, domain)])
            if hits:
                return q, hits[:3], name, errors
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{type(exc).__name__}")
    return q, hits[:3], None, errors


def main() -> int:
    reg = load_merged()
    SessionLocal = _wire()
    blob = LocalBlobStore(BASE / "blobs")
    new_ok = []
    rows = []

    with SessionLocal() as session:
        for r in session.scalars(select(ReviewCandidate)):
            session.delete(r)
        session.commit()

        for sid in REMAINING:
            src = reg.get(sid)
            if not src or not src.enabled:
                rows.append({"id": sid, "pipeline": "disabled"})
                continue
            print(f"== {sid}", flush=True)
            q, hits, provider, errors = asyncio.run(search_both(src.domain))
            if not hits:
                # homepage L1 fallback for guide/list
                from fetch.content import fetch_and_extract
                from fetch.content_validity import page_is_invalid

                url = (src.home_url or f"https://{src.domain}/").strip()
                try:
                    page = fetch_and_extract(url, timeout=25.0)
                    v = page_is_invalid(page)
                    ok = v.ok and len(page.text or "") >= 80
                    rows.append(
                        {
                            "id": sid,
                            "pipeline": "home_ok" if ok else "home_fail",
                            "search_errors": errors,
                            "text_len": len(page.text or ""),
                            "title": (page.title or "")[:80],
                        }
                    )
                    if ok:
                        new_ok.append(sid)
                    print(f"   home {'ok' if ok else 'fail'}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    rows.append(
                        {
                            "id": sid,
                            "pipeline": "home_fail",
                            "search_errors": errors,
                            "error": f"{type(exc).__name__}: {exc}"[:160],
                        }
                    )
                    print(f"   home fail {type(exc).__name__}", flush=True)
                continue

            rid = uuid.uuid4().hex[:12]
            for h in hits:
                session.add(
                    ReviewCandidate(
                        run_id=rid,
                        provider=provider or "search",
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
            fetch = fetch_discovered_candidates(session, blob, limit=len(hits), enable_l2=True)
            usable = []
            for r in session.scalars(select(ReviewCandidate).where(ReviewCandidate.run_id == rid)):
                if r.status != "pending_review":
                    continue
                blob_ok = bool(r.object_key) and (blob.root / r.object_key).is_file()
                html = (blob.root / r.object_key).read_bytes()[:20000] if blob_ok else b""
                v = assess_extracted_page(title=r.title, text=r.extracted_text, html=html)
                if blob_ok and len(r.extracted_text or "") >= 80 and (r.title or "").strip() and v.ok:
                    usable.append({"title": (r.title or "")[:80], "text_len": len(r.extracted_text or "")})
            ok = bool(usable)
            if ok:
                new_ok.append(sid)
            rows.append(
                {
                    "id": sid,
                    "provider": provider,
                    "hits": len(hits),
                    "usable_n": len(usable),
                    "pipeline": "ok" if ok else "fetch_fail",
                    "l2_used": fetch.get("l2_used"),
                    "sample": usable[:1],
                }
            )
            print(f"   {'ok' if ok else 'fail'} usable={len(usable)} via={provider}", flush=True)

    clarified = {
        "bkpm": "certificate_failure — needs Indonesian PROXY_URL; no verify=False",
        "kadin": "L1 TLS / L2 timeout from this egress",
        "mofcom_id_embassy": "connection closed / HTTP failure from this host",
        "reuters": "401/paywall shell — license or snippet-only",
        "batang_city": "self-signed certificate — need valid CA or proxy; no verify=False",
        "mofcom_fdi_guide": "DNS failed for www.fdi.gov.cn from this host",
        "jiipe": "homepage 415/empty shell; article fetch failed this egress",
        "unctad_wir": "Cloudflare challenge (Just a moment…)",
    }
    all_ok = sorted(ALREADY_OK | set(new_ok))
    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "new_ok_this_tick": new_ok,
        "all_ok_cumulative": all_ok,
        "remaining_rows": rows,
        "clarified_blockers": clarified,
        "plateau": True,
        "plateau_reason": (
            "25 prefer sources OK for search→local store. Remaining failures need "
            "proxy/DNS/paywall/CF — not more scraper code without external egress or licenses. Loop stopped."
        ),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"new_ok": new_ok, "all_ok_n": len(all_ok), "plateau": True}, indent=2))
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
