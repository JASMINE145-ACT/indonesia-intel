"""Inspect partial e2e probe DBs + finish a fast capability report."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import Base
from app.models import ReviewCandidate
from fetch.content_validity import assess_extracted_page
from jobs.fetch_candidates import fetch_discovered_candidates
from jobs.poll_rss import poll_rss_sources
from jobs.ingest_search import run_search_ingest
from providers.factory import available_provider_names, get_provider
from dedup.url import normalize_url, url_hash
from storage.blob import LocalBlobStore
import asyncio

QUERY = "China Indonesia investment nickel EV"
OUT = ROOT / "evidence" / "e2e-keyword-to-local.json"
BASE = ROOT / "data" / "_e2e_probe"


def inspect_db(name: str) -> dict:
    db = BASE / name / "e2e.db"
    blob_root = BASE / f"blobs_{name.replace('s_', '')}" if name.startswith("s_") else BASE / f"blobs_{name}"
    # map names: rss→blobs_rss, s_exa→blobs_exa, seed→blobs_seed
    mapping = {
        "rss": BASE / "blobs_rss",
        "s_exa": BASE / "blobs_exa",
        "s_tavily": BASE / "blobs_tavily",
        "s_mock": BASE / "blobs_mock",
        "seed": BASE / "blobs_seed",
        "seed_fast": BASE / "blobs_seed_fast",
    }
    blob_root = mapping.get(name, blob_root)
    if not db.exists():
        return {"name": name, "exists": False}
    eng = create_engine(f"sqlite:///{db.as_posix()}", future=True)
    with eng.connect() as c:
        counts = dict(c.execute(text("select status, count(*) from review_candidates group by status")).all())
        rows = c.execute(
            text(
                "select id, source_id, provider, status, title, "
                "length(coalesce(extracted_text,'')) as text_len, object_key, "
                "canonical_url, snippet from review_candidates order by id"
            )
        ).mappings().all()
    articles = []
    for r in rows:
        blob_ok = bool(r["object_key"]) and (blob_root / r["object_key"]).is_file()
        title = (r["title"] or "").strip()
        text_len = int(r["text_len"] or 0)
        html = b""
        if blob_ok:
            html = (blob_root / r["object_key"]).read_bytes()[:20000]
        extracted = ""
        # need extracted_text from DB
        with eng.connect() as c2:
            et = c2.execute(
                text("select extracted_text from review_candidates where id=:i"),
                {"i": r["id"]},
            ).scalar()
            extracted = et or ""
        v = assess_extracted_page(title=title, text=extracted, html=html)
        usable = (
            r["status"] == "pending_review"
            and blob_ok
            and text_len >= 40
            and bool(title)
            and v.ok
        )
        articles.append(
            {
                "source_id": r["source_id"],
                "provider": r["provider"],
                "status": r["status"],
                "title": title[:120],
                "url": r["canonical_url"],
                "text_len": text_len,
                "blob_exists": blob_ok,
                "usable_local_article": usable,
                "error_or_snippet": (None if usable else (v.error_type or (r["snippet"] or "")[:120])),
            }
        )
    return {
        "name": name,
        "exists": True,
        "counts": counts,
        "usable": [a for a in articles if a["usable_local_article"]],
        "all": articles,
    }


def _wire(tmp: Path):
    tmp.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{(tmp / 'e2e.db').as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def run_seed_fast() -> dict:
    """L1-only prefer seeds — no Scrapling browser waits."""
    seeds = [
        ("antara", "https://en.antaranews.com/"),
        ("esdm", "https://www.esdm.go.id/"),
        ("imip", "https://imip.co.id/"),
        ("kadin", "https://www.kadin.id/"),
        ("world_bank", "https://www.worldbank.org/en/country/indonesia"),
    ]
    SessionLocal = _wire(BASE / "seed_fast")
    blob = LocalBlobStore(BASE / "blobs_seed_fast")
    with SessionLocal() as session:
        rid = uuid.uuid4().hex[:12]
        for sid, url in seeds:
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
        fetch = fetch_discovered_candidates(session, blob, limit=20, enable_l2=False)
    return {"fetch": fetch, "inspect": inspect_db("seed_fast")}


def run_rss_if_needed() -> dict:
    existing = inspect_db("rss")
    if existing.get("usable"):
        return {"reused": True, "inspect": existing}
    SessionLocal = _wire(BASE / "rss")
    blob = LocalBlobStore(BASE / "blobs_rss")
    with SessionLocal() as session:
        # wipe
        for r in session.scalars(select(ReviewCandidate)):
            session.delete(r)
        session.commit()
        poll = poll_rss_sources(session, source_ids=["antara"], limit_per_source=5)
        fetch = fetch_discovered_candidates(session, blob, limit=5, enable_l2=False)
    return {"reused": False, "poll": poll, "fetch": fetch, "inspect": inspect_db("rss")}


def run_mock() -> dict:
    from app.config import settings

    SessionLocal = _wire(BASE / "s_mock")
    blob = LocalBlobStore(BASE / "blobs_mock")
    with SessionLocal() as session:
        for r in session.scalars(select(ReviewCandidate)):
            session.delete(r)
        session.commit()
        provider = get_provider("mock")
        ingest = asyncio.run(run_search_ingest(session, provider, QUERY))
        fetch = fetch_discovered_candidates(session, blob, limit=3, enable_l2=False)
    return {"ingest": ingest, "fetch": fetch, "inspect": inspect_db("s_mock")}


def main() -> int:
    from app.config import settings

    print("1) inspect prior...", flush=True)
    prior = {n: inspect_db(n) for n in ("rss", "s_exa", "s_tavily", "s_mock", "seed")}

    print("2) RSS Antara (L1 only)...", flush=True)
    rss = run_rss_if_needed()

    print("3) mock keyword path...", flush=True)
    mock = run_mock()

    print("4) prefer L1 seed (no L2)...", flush=True)
    seed = run_seed_fast()

    available = available_provider_names(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )

    rss_usable = rss["inspect"].get("usable") or []
    seed_usable = [a for a in (seed["inspect"].get("all") or []) if a["usable_local_article"]]
    mock_usable = mock["inspect"].get("usable") or []

    # classify search providers without calling network when keys missing
    search_channels = []
    for pname, key_set in (("exa", bool(settings.exa_api_key)), ("tavily", bool(settings.tavily_api_key))):
        if not key_set:
            search_channels.append(
                {
                    "channel": f"search:{pname}",
                    "supports_keyword_input": True,
                    "pipeline_ok": False,
                    "blocker": f"{pname.upper()}_API_KEY empty in .env",
                }
            )
        else:
            search_channels.append(
                {
                    "channel": f"search:{pname}",
                    "supports_keyword_input": True,
                    "pipeline_ok": "not_retested_keys_present",
                    "note": "Key present — retest live search separately",
                }
            )

    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "user_goal": "keyword → find articles → store title+body locally",
        "query": QUERY,
        "configured_search_providers": available,
        "exa_key_set": bool(settings.exa_api_key),
        "tavily_key_set": bool(settings.tavily_api_key),
        "prior_partial": {
            k: {"counts": v.get("counts"), "usable_n": len(v.get("usable") or [])}
            for k, v in prior.items()
            if v.get("exists")
        },
        "channels": {
            "prefer_rss_antara": {
                "supports_keyword_input": "post_filter_only",
                "pipeline_ok": bool(rss_usable),
                "usable_articles": rss_usable[:5],
                "detail": {k: rss[k] for k in rss if k != "inspect"},
            },
            "search_providers": search_channels,
            "search_mock": {
                "supports_keyword_input": True,
                "pipeline_ok": bool(mock_usable),
                "note": "synthetic URLs — proves local store plumbing, not real web",
                "usable_n": len(mock_usable),
            },
            "prefer_seed_l1": {
                "supports_keyword_input": False,
                "pipeline_ok": bool(seed_usable),
                "by_source": {
                    a["source_id"]: {
                        "usable": a["usable_local_article"],
                        "title": a["title"],
                        "text_len": a["text_len"],
                        "error": a["error_or_snippet"],
                    }
                    for a in (seed["inspect"].get("all") or [])
                },
            },
        },
        "verdict": {
            "full_keyword_to_real_article_local_today": False,
            "reason": (
                "EXA_API_KEY and TAVILY_API_KEY are empty — cannot discover real web "
                "articles from a keyword. Prefer RSS (Antara) can discover+store without "
                "keyword search APIs; keyword is only a soft post-filter on titles."
            ),
            "what_works_now": [
                {
                    "path": "Antara RSS → fetch → SQLite + blob",
                    "keyword": "optional title filter only",
                    "ok": bool(rss_usable),
                    "sample_titles": [a["title"] for a in rss_usable[:3]],
                },
                {
                    "path": "Prefer site URL → fetch L1 → local store",
                    "keyword": "no",
                    "ok_sources": [a["source_id"] for a in seed_usable],
                },
                {
                    "path": "mock search → fetch → local store",
                    "keyword": "yes (fake hits)",
                    "ok": bool(mock_usable),
                },
            ],
            "to_unlock_keyword_path": "Set EXA_API_KEY or TAVILY_API_KEY in indonesia-intel/.env then re-run search+fetch",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out["verdict"], ensure_ascii=False, indent=2))
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
