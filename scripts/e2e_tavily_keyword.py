"""Quick Tavily keyword → fetch → local store probe (no secrets printed)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
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
OUT = ROOT / "evidence" / "e2e-tavily-keyword.json"
BASE = ROOT / "data" / "_e2e_probe" / "tavily_live"


def main() -> int:
    tlen = len(settings.tavily_api_key or "")
    print(f"tavily_key_len={tlen} exa_key_len={len(settings.exa_api_key or '')}", flush=True)
    if tlen < 8:
        print("FAIL: TAVILY_API_KEY still not loaded", flush=True)
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

    provider = get_provider("tavily", tavily_api_key=settings.tavily_api_key)
    with SessionLocal() as session:
        print("searching Tavily...", flush=True)
        ingest = asyncio.run(run_search_ingest(session, provider, QUERY))
        print(f"ingest={ingest}", flush=True)
        print("fetching L1...", flush=True)
        fetch = fetch_discovered_candidates(session, blob, limit=5, enable_l2=False)
        summary = {k: fetch[k] for k in ("fetched", "failed", "total", "l2_used")}
        print(f"fetch={summary}", flush=True)
        usable = []
        for r in session.scalars(
            select(ReviewCandidate).where(ReviewCandidate.status == "pending_review")
        ):
            blob_ok = bool(r.object_key) and (blob.root / r.object_key).is_file()
            html = (blob.root / r.object_key).read_bytes()[:20000] if blob_ok else b""
            v = assess_extracted_page(title=r.title, text=r.extracted_text, html=html)
            ok = (
                blob_ok
                and len(r.extracted_text or "") >= 40
                and bool((r.title or "").strip())
                and v.ok
            )
            usable.append(
                {
                    "title": (r.title or "")[:120],
                    "url": r.canonical_url,
                    "text_len": len(r.extracted_text or ""),
                    "blob_exists": blob_ok,
                    "usable": ok,
                    "domain": r.source_domain,
                }
            )

    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "tavily_key_loaded": True,
        "ingest": ingest,
        "fetch": {k: fetch[k] for k in ("fetched", "failed", "total", "l2_used")},
        "usable_articles": [u for u in usable if u["usable"]],
        "pipeline_ok": any(u["usable"] for u in usable),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "pipeline_ok": out["pipeline_ok"],
                "fetched": out["fetch"]["fetched"],
                "failed": out["fetch"]["failed"],
                "usable_n": len(out["usable_articles"]),
                "titles": [u["title"] for u in out["usable_articles"][:5]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0 if out["pipeline_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
