"""Phase 3 vertical slice — WANd.INTEL.VERTICAL_SLICE.001"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.main import create_app
from app.models import FormalEvent, ReviewCandidate, ReviewDecision
from jobs.fetch_candidates import fetch_discovered_candidates
from storage.blob import LocalBlobStore

FIXTURE_HTML = b"""<!doctype html><html><head><title>Plant News</title></head>
<body><article><p>Chinese company builds factory in Indonesia Subang.</p></article></body></html>"""


def test_vertical_slice_mvp(tmp_path) -> None:
    db_path = tmp_path / "slice.db"
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False}
    )
    from app import db as dbmod

    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)

    blob = LocalBlobStore(tmp_path / "blobs")
    session = dbmod.SessionLocal()
    url = "https://example.com/news/plant"
    session.add(
        ReviewCandidate(
            run_id="slice1",
            provider="brave_mock",
            query="test",
            original_url=url,
            canonical_url=url,
            url_hash="slicehash001",
            title="Plant News",
            snippet="",
            status="discovered",
            raw_search_json="{}",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    summary = fetch_discovered_candidates(
        session, blob, resolve_dns=False, html_overrides={url: FIXTURE_HTML}
    )
    assert summary["fetched"] == 1
    cid = session.scalar(select(ReviewCandidate)).id
    session.close()

    client = TestClient(create_app())
    headers = {"X-API-Key": settings.api_key}
    assert client.get("/candidates", headers=headers).status_code == 200
    assert client.post(f"/candidates/{cid}/confirm").status_code == 401
    assert client.post(f"/candidates/{cid}/confirm", headers=headers).json()["status"] == "confirmed"

    session = dbmod.SessionLocal()
    assert session.scalar(select(ReviewDecision)) is not None
    assert session.scalar(select(FormalEvent)).candidate_id == cid
    session.close()
