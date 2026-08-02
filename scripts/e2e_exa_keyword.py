"""Finish Exa keyword → fetch → local store check (L1 only, short)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import Base
from app.models import ReviewCandidate
from fetch.content_validity import assess_extracted_page
from jobs.fetch_candidates import fetch_discovered_candidates
from jobs.ingest_search import run_search_ingest
from providers.factory import get_provider
from storage.blob import LocalBlobStore

QUERY = "China Indonesia nickel investment"
OUT = ROOT / "evidence" / "e2e-exa-keyword.json"
BASE = ROOT / "data" / "_e2e_probe" / "exa_live"


def main() -> int:
    print(
        f"exa_key_len={len(settings.exa_api_key or '')} "
        f"tavily_key_len={len(settings.tavily_api_key or '')}",
        flush=True,
    )
    # Inspect prior partial Exa run
    prior_db = ROOT / "data" / "_e2e_probe" / "s_exa" / "e2e.db"
    prior_blob = ROOT / "data" / "_e2e_probe" / "blobs_exa"
    prior = []
    if prior_db.exists():
        eng = create_engine(f"sqlite:///{prior_db.as_posix()}", future=True)
        with eng.connect() as c:
            rows = c.execute(
                text(
                    "select source_id, status, title, length(coalesce(extracted_text,'')) tl, "
                    "object_key, canonical_url from review_candidates "
                    "where status='pending_review'"
                )
            ).mappings().all()
            for r in rows:
                blob_ok = bool(r["object_key"]) and (prior_blob / r["object_key"]).is_file()
                prior.append(
                    {
                        "title": (r["title"] or "")[:120],
                        "url": r["canonical_url"],
                        "text_len": r["tl"],
                        "blob_exists": blob_ok,
                    }
                )
        print(f"prior usable pending_review: {len(prior)}", flush=True)

    if not settings.exa_api_key:
        out = {
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_ok": False,
            "blocker": "EXA_API_KEY empty",
            "prior_partial_usable": prior,
        }
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    BASE.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{(BASE / 'e2e.db').as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    blob = LocalBlobStore(BASE / "blobs")

    provider = get_provider("exa", exa_api_key=settings.exa_api_key)
    with SessionLocal() as session:
        print("searching Exa...", flush=True)
        ingest = asyncio.run(run_search_ingest(session, provider, QUERY))
        print(f"ingest={ingest}", flush=True)
        # only fetch first 5 discovered
        print("fetching L1 only...", flush=True)
        fetch = fetch_discovered_candidates(session, blob, limit=5, enable_l2=False)
        print(f"fetch={ {k: fetch[k] for k in ('fetched','failed','total','l2_used')} }", flush=True)

        usable = []
        for r in session.scalars(
            select(ReviewCandidate).where(ReviewCandidate.status == "pending_review")
        ):
            blob_ok = bool(r.object_key) and (blob.root / r.object_key).is_file()
            html = (blob.root / r.object_key).read_bytes()[:20000] if blob_ok else b""
            v = assess_extracted_page(title=r.title, text=r.extracted_text, html=html)
            ok = blob_ok and len(r.extracted_text or "") >= 40 and bool((r.title or "").strip()) and v.ok
            usable.append(
                {
                    "title": (r.title or "")[:120],
                    "url": r.canonical_url,
                    "text_len": len(r.extracted_text or ""),
                    "blob": r.object_key,
                    "blob_exists": blob_ok,
                    "usable": ok,
                    "domain": r.source_domain,
                }
            )

    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "ingest": ingest,
        "fetch": {k: fetch[k] for k in ("fetched", "failed", "total", "l2_used")},
        "usable_articles": [u for u in usable if u["usable"]],
        "all_pending": usable,
        "prior_partial_usable": prior,
        "pipeline_ok": any(u["usable"] for u in usable) or len(prior) > 0,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("pipeline_ok", "usable_articles", "prior_partial_usable")}, ensure_ascii=False, indent=2))
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
