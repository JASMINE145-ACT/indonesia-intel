from sqlalchemy import create_engine

from app.db import Base, _add_missing_columns
from app import models  # noqa: F401 — register ORM tables on Base.metadata


def test_add_missing_columns_upgrades_pre_prd5_formal_events_table(tmp_path) -> None:
    """Regression: this project has no Alembic, so `create_all` alone would leave
    an existing formal_events table stuck on the old thin schema forever once the
    PRD §5 structured fields were added to the model — silently breaking confirm
    on any already-populated data/intel.db. init_db() must self-heal this."""
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE formal_events (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER NOT NULL,
                title VARCHAR(1024) NOT NULL,
                canonical_url TEXT NOT NULL,
                provider VARCHAR(64) NOT NULL,
                object_key VARCHAR(128),
                created_at DATETIME NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO formal_events (candidate_id, title, canonical_url, provider, created_at) "
            "VALUES (1, 'old row', 'https://example.com', 'mock', '2026-01-01 00:00:00')"
        )

    Base.metadata.create_all(bind=engine)  # only creates tables that don't exist yet
    _add_missing_columns(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info("formal_events")')}
        assert {"industry", "event_type", "project_stage", "company_id", "is_public"} <= cols

        row = conn.exec_driver_sql("SELECT title, is_public, industry FROM formal_events").one()
        assert row.title == "old row"
        assert row.is_public == 1  # server_default backfilled the pre-existing row
        assert row.industry is None


def test_add_missing_columns_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(bind=engine)

    _add_missing_columns(engine)
    _add_missing_columns(engine)  # second pass over an already-current schema must not raise


def test_add_missing_columns_upgrades_review_candidates_fetch_status(tmp_path) -> None:
    """Additive fetch_status / fetch_error_type must self-heal populated DBs."""
    db_path = tmp_path / "old_rc.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE review_candidates (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR(64) NOT NULL,
                provider VARCHAR(64) NOT NULL,
                query VARCHAR(512) NOT NULL,
                original_url TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                url_hash VARCHAR(64) NOT NULL,
                title VARCHAR(1024) NOT NULL,
                snippet TEXT NOT NULL DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'discovered',
                raw_search_json TEXT NOT NULL DEFAULT '{}',
                is_public_source BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO review_candidates "
            "(run_id, provider, query, original_url, canonical_url, url_hash, title, "
            "snippet, status, created_at, updated_at) "
            "VALUES ('r1', 'mock', 'q', 'https://example.com/a', 'https://example.com/a', "
            "'h1', 't', '', 'discovered', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )

    Base.metadata.create_all(bind=engine)
    _add_missing_columns(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info("review_candidates")')}
        assert {"fetch_status", "fetch_error_type"} <= cols
        row = conn.exec_driver_sql(
            "SELECT fetch_status, fetch_error_type FROM review_candidates WHERE url_hash='h1'"
        ).one()
        assert row.fetch_status == "not_attempted"
        assert row.fetch_error_type is None


def test_add_missing_columns_upgrades_review_candidates_discovery(tmp_path) -> None:
    """AC-06: discovery_method / resolved_url / resolution_status / published_at."""
    db_path = tmp_path / "old_disc.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE review_candidates (
                id INTEGER PRIMARY KEY,
                run_id VARCHAR(64) NOT NULL,
                provider VARCHAR(64) NOT NULL,
                query VARCHAR(512) NOT NULL,
                original_url TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                url_hash VARCHAR(64) NOT NULL,
                title VARCHAR(1024) NOT NULL,
                snippet TEXT NOT NULL DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'discovered',
                fetch_status VARCHAR(32) NOT NULL DEFAULT 'not_attempted',
                raw_search_json TEXT NOT NULL DEFAULT '{}',
                is_public_source BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            "INSERT INTO review_candidates "
            "(run_id, provider, query, original_url, canonical_url, url_hash, title, "
            "snippet, status, created_at, updated_at) "
            "VALUES ('r1', 'mock', 'q', 'https://example.com/a', 'https://example.com/a', "
            "'h1', 't', '', 'discovered', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )

    Base.metadata.create_all(bind=engine)
    _add_missing_columns(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info("review_candidates")')}
        assert {
            "discovery_method",
            "resolved_url",
            "resolution_status",
            "published_at",
        } <= cols
        row = conn.exec_driver_sql(
            "SELECT discovery_method, resolution_status, resolved_url, published_at "
            "FROM review_candidates WHERE url_hash='h1'"
        ).one()
        assert row.discovery_method == "rss"
        assert row.resolution_status == "not_required"
        assert row.resolved_url is None
        assert row.published_at is None
