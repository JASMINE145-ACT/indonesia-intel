"""WANd.INTEL.QUERY_EXPAND.001"""

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Company
from jobs.query_expand import expand_queries


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_expand_disabled_returns_original() -> None:
    assert expand_queries("山海图", enabled=False) == ["山海图"]


def test_expand_templates_without_company(tmp_path) -> None:
    session = _session(tmp_path)
    out = expand_queries("山海图科技", session=session, max_variants=4)
    assert out[0] == "山海图科技"
    assert len(out) >= 2
    assert any("Indonesia" in q for q in out)


def test_expand_uses_company_aliases(tmp_path) -> None:
    session = _session(tmp_path)
    session.add(
        Company(
            name_cn="北京山海图科技有限公司",
            name_en="Beijing Shanhaitu Technology",
            name_id="PT Shanhaitu",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()
    out = expand_queries("山海图", session=session, max_variants=4)
    joined = " | ".join(out)
    assert "Beijing Shanhaitu Technology" in joined
    assert "PT Shanhaitu" in joined or "Indonesia" in joined


def test_expand_entity_alias_byd() -> None:
    out = expand_queries("比亚迪 印尼", max_variants=4)
    assert any("BYD" in q for q in out)
