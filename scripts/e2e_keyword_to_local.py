"""E2E probe: keyword → discover articles → fetch title/body → local store.

Answers: which channels can currently deliver usable stored articles.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Base
from app.models import ReviewCandidate
from jobs.fetch_candidates import fetch_discovered_candidates
from jobs.poll_rss import poll_rss_sources
from jobs.ingest_search import run_search_ingest
from providers.factory import available_provider_names, get_provider
from storage.blob import LocalBlobStore
import asyncio


QUERY = "China Indonesia investment nickel EV"
OUT = ROOT / "evidence" / "e2e-keyword-to-local.json"


def _wire(tmp: Path):
    tmp.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{(tmp / 'e2e.db').as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _stored_ok(session, blob: LocalBlobStore) -> list[dict]:
    rows = list(
        session.scalars(
            select(ReviewCandidate).where(ReviewCandidate.status == "pending_review")
        )
    )
    out = []
    for r in rows:
        blob_ok = bool(r.object_key) and (blob.root / r.object_key).is_file()
        text_len = len(r.extracted_text or "")
        title = (r.title or "").strip()
        usable = blob_ok and text_len >= 40 and bool(title)
        # re-check block markers on stored fields
        from fetch.content_validity import assess_extracted_page

        html = b""
        if blob_ok:
            html = (blob.root / r.object_key).read_bytes()[:20000]
        v = assess_extracted_page(title=title, text=r.extracted_text, html=html)
        usable = usable and v.ok
        out.append(
            {
                "id": r.id,
                "source_id": r.source_id,
                "provider": r.provider,
                "title": title[:120],
                "url": r.canonical_url,
                "text_len": text_len,
                "blob": r.object_key,
                "blob_exists": blob_ok,
                "usable_local_article": usable,
                "error_type": None if usable else (v.error_type or "insufficient_content"),
                "snippet_via": (r.snippet or "")[:80],
            }
        )
    return out


def channel_rss_antara(SessionLocal, blob) -> dict:
    with SessionLocal() as session:
        poll = poll_rss_sources(session, source_ids=["antara"], limit_per_source=8)
        # keyword filter soft: keep titles matching any keyword token
        tokens = [t.lower() for t in ("china", "chinese", "indonesia", "invest", "nickel", "ev", "battery")]
        rows = list(
            session.scalars(
                select(ReviewCandidate).where(ReviewCandidate.status == "discovered")
            )
        )
        keep = 0
        for r in rows:
            hay = f"{r.title} {r.snippet}".lower()
            if any(t in hay for t in tokens):
                keep += 1
            else:
                # leave non-matching discovered; fetch will still pull them — delete for clean probe
                session.delete(r)
        session.commit()
        # if none matched keywords, re-poll and fetch top N anyway (prove pipeline)
        remaining = list(
            session.scalars(
                select(ReviewCandidate).where(ReviewCandidate.status == "discovered")
            )
        )
        mode = "keyword_filtered" if remaining else "latest_unfiltered"
        if not remaining:
            poll2 = poll_rss_sources(session, source_ids=["antara"], limit_per_source=5)
            poll = {"first": poll, "refill": poll2}
            mode = "latest_unfiltered"
        fetch = fetch_discovered_candidates(session, blob, limit=5, enable_l2=True)
        stored = _stored_ok(session, blob)
        return {
            "channel": "prefer_rss:antara + fetch",
            "supports_keyword_input": mode == "keyword_filtered",
            "keyword_mode": mode,
            "poll": poll,
            "fetch": {k: fetch[k] for k in ("fetched", "failed", "total", "l2_used")},
            "usable_articles": [s for s in stored if s["usable_local_article"]],
            "pipeline_ok": any(s["usable_local_article"] for s in stored),
        }


def channel_search(SessionLocal, blob, provider_name: str) -> dict:
    from app.config import settings

    try:
        provider = get_provider(
            provider_name,
            brave_enabled=settings.brave_enabled,
            brave_api_key=settings.brave_api_key,
            exa_api_key=settings.exa_api_key,
            tavily_api_key=settings.tavily_api_key,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "channel": f"search:{provider_name}",
            "supports_keyword_input": True,
            "pipeline_ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    with SessionLocal() as session:
        # clear previous discovered in this temp db not needed (fresh)
        summary = asyncio.run(run_search_ingest(session, provider, QUERY))
        fetch = fetch_discovered_candidates(session, blob, limit=5, enable_l2=True)
        stored = _stored_ok(session, blob)
        usable = [s for s in stored if s["usable_local_article"]]
        return {
            "channel": f"search:{provider_name} + fetch",
            "supports_keyword_input": True,
            "provider_class": type(provider).__name__,
            "ingest": summary,
            "fetch": {k: fetch[k] for k in ("fetched", "failed", "total", "l2_used")},
            "usable_articles": usable[:5],
            "pipeline_ok": bool(usable),
            "note": (
                "mock results are synthetic — not real web articles"
                if provider_name == "mock" or "Mock" in type(provider).__name__
                else None
            ),
        }


def channel_seed_prefer_urls(SessionLocal, blob) -> dict:
    """Seed home/article URLs from prefer sources known-good, then fetch."""
    seeds = [
        ("antara", "https://en.antaranews.com/", "stealthy"),
        ("esdm", "https://www.esdm.go.id/", "http"),
        ("imip", "https://imip.co.id/", "http"),
        ("iea_id", "https://www.iea.org/countries/indonesia", "stealthy"),
        ("kompas", "https://www.kompas.com/", "stealthy"),
        ("kadin", "https://www.kadin.id/", "http"),
        ("idx", "https://www.idx.co.id/", "stealthy"),
        ("mofcom_id_embassy", "http://id.mofcom.gov.cn/", "dynamic"),
    ]
    from app.models import ReviewCandidate
    from dedup.url import normalize_url, url_hash

    with SessionLocal() as session:
        rid = uuid.uuid4().hex[:12]
        for sid, url, _mode in seeds:
            session.add(
                ReviewCandidate(
                    run_id=rid,
                    provider="seed",
                    query=QUERY,
                    original_url=url,
                    canonical_url=normalize_url(url),
                    url_hash=url_hash(url),
                    title="",
                    snippet=f"seed:{sid}",
                    source_id=sid,
                    status="discovered",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        session.commit()
        fetch = fetch_discovered_candidates(session, blob, limit=20, enable_l2=True)
        stored = _stored_ok(session, blob)
        by_source = {}
        for s in stored:
            sid = s["source_id"] or "?"
            by_source[sid] = {
                "usable_local_article": s["usable_local_article"],
                "title": s["title"],
                "text_len": s["text_len"],
                "blob_exists": s["blob_exists"],
                "error_type": s["error_type"],
                "via": s["snippet_via"],
            }
        # also include fetch_failed
        failed = list(
            session.scalars(
                select(ReviewCandidate).where(ReviewCandidate.status == "fetch_failed")
            )
        )
        for r in failed:
            by_source[r.source_id or "?"] = {
                "usable_local_article": False,
                "title": (r.title or "")[:80],
                "text_len": len(r.extracted_text or ""),
                "blob_exists": False,
                "error_type": (r.snippet or "")[:120],
                "via": "fetch_failed",
            }
        return {
            "channel": "prefer_seed_urls + fetch(L1/L2)",
            "supports_keyword_input": False,
            "note": "No keyword discovery — only proves title/body local store for known URLs",
            "fetch": {k: fetch[k] for k in ("fetched", "failed", "total", "l2_used")},
            "by_source": by_source,
            "pipeline_ok": any(v.get("usable_local_article") for v in by_source.values()),
        }


def main() -> int:
    from app.config import settings

    tmp = ROOT / "data" / "_e2e_probe"
    tmp.mkdir(parents=True, exist_ok=True)
    blob = LocalBlobStore(tmp / "blobs")
    SessionLocal = _wire(tmp)

    available = available_provider_names(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )

    channels = []
    # Fresh DB for each channel
    SessionLocal = _wire(tmp / "rss")
    blob_rss = LocalBlobStore(tmp / "blobs_rss")
    channels.append(channel_rss_antara(SessionLocal, blob_rss))

    for pname in ("exa", "tavily", "mock"):
        SessionLocal = _wire(tmp / f"s_{pname}")
        blob_s = LocalBlobStore(tmp / f"blobs_{pname}")
        channels.append(channel_search(SessionLocal, blob_s, pname))

    SessionLocal = _wire(tmp / "seed")
    blob_seed = LocalBlobStore(tmp / "blobs_seed")
    channels.append(channel_seed_prefer_urls(SessionLocal, blob_seed))

    # Who can do full keyword→article→local?
    keyword_ready = [
        c
        for c in channels
        if c.get("supports_keyword_input") and c.get("pipeline_ok") and not (c.get("note") or "").startswith("mock")
    ]
    store_ready_sources = []
    seed = next((c for c in channels if c["channel"].startswith("prefer_seed")), {})
    for sid, info in (seed.get("by_source") or {}).items():
        if info.get("usable_local_article"):
            store_ready_sources.append(sid)

    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "user_goal": "keyword → find articles → store title+body locally",
        "query": QUERY,
        "configured_search_providers": available,
        "exa_key_set": bool(settings.exa_api_key),
        "tavily_key_set": bool(settings.tavily_api_key),
        "channels": channels,
        "verdict": {
            "full_keyword_to_local_real_web": bool(keyword_ready),
            "full_keyword_channels": [c["channel"] for c in keyword_ready],
            "keyword_to_local_via_mock_only": any(
                c.get("pipeline_ok") and "mock" in c.get("channel", "") for c in channels
            ),
            "prefer_rss_to_local": next(
                (c.get("pipeline_ok") for c in channels if "antara" in c.get("channel", "")),
                False,
            ),
            "sources_that_can_store_title_body_today": store_ready_sources,
            "blocker_for_keyword_path": (
                None
                if keyword_ready
                else "EXA_API_KEY and TAVILY_API_KEY empty in .env — wide keyword search cannot hit real web"
            ),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["verdict"], ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
