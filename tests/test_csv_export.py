import csv
import io

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import FormalEvent
from jobs.csv_export import EVENT_EXPORT_COLUMNS, export_events_csv


def _session(tmp_path):
    db = tmp_path / "export.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_export_events_csv_header_and_row(tmp_path) -> None:
    session = _session(tmp_path)
    session.add(
        FormalEvent(
            candidate_id=1,
            title="比亚迪开工",
            canonical_url="https://example.com/1",
            provider="mock",
            industry="汽车、工程机械与交通装备",
            event_type="开工建设",
        )
    )
    session.commit()

    text = export_events_csv(session)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == EVENT_EXPORT_COLUMNS
    assert len(rows) == 2
    assert rows[1][EVENT_EXPORT_COLUMNS.index("title")] == "比亚迪开工"


def test_export_events_csv_applies_filters(tmp_path) -> None:
    session = _session(tmp_path)
    session.add_all(
        [
            FormalEvent(
                candidate_id=1,
                title="事件A",
                canonical_url="https://example.com/1",
                provider="mock",
                industry="汽车、工程机械与交通装备",
            ),
            FormalEvent(
                candidate_id=2,
                title="事件B",
                canonical_url="https://example.com/2",
                provider="mock",
                industry="新能源电池与材料",
            ),
        ]
    )
    session.commit()

    text = export_events_csv(session, industry="新能源电池与材料")
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 2  # header + 1 matching row
    assert rows[1][EVENT_EXPORT_COLUMNS.index("title")] == "事件B"


def test_export_events_csv_empty_still_has_header(tmp_path) -> None:
    session = _session(tmp_path)
    text = export_events_csv(session)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows == [EVENT_EXPORT_COLUMNS]
