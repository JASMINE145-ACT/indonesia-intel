from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from jobs.manual_intake import manual_add_pdf

FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "sample_announcement.pdf"


def _session(tmp_path):
    db = tmp_path / "pdf.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_manual_add_pdf_pending(tmp_path) -> None:
    session = _session(tmp_path)
    assert FIXTURE_PDF.is_file()
    row = manual_add_pdf(session, str(FIXTURE_PDF))
    assert row.status == "pending_review"
    assert row.provider == "manual_pdf"
    assert row.extracted_text and len(row.extracted_text) >= 20
    assert row.title


def test_manual_add_pdf_rejects_empty_bytes(tmp_path) -> None:
    session = _session(tmp_path)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(ValueError):
        manual_add_pdf(session, str(empty))


def test_manual_add_pdf_rejects_path_traversal(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError, match="traversal"):
        manual_add_pdf(session, str(tmp_path / ".." / ".." / "Windows" / "win.ini"))
