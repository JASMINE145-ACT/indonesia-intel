"""Tests for L1 PDF extraction (cninfo-style disclosure)."""

from pathlib import Path

from fetch.content import fetch_and_extract
from fetch.pdf import extract_pdf_text, looks_like_pdf

FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "sample_announcement.pdf"


def _minimal_pdf_with_text() -> bytes:
    if not FIXTURE_PDF.is_file():
        from tests._gen_pdf_fixture import build_pdf

        FIXTURE_PDF.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PDF.write_bytes(build_pdf())
    return FIXTURE_PDF.read_bytes()


def test_looks_like_pdf() -> None:
    data = b"%PDF-1.4...."
    assert looks_like_pdf("https://x/a.pdf", data, "application/pdf")
    assert not looks_like_pdf("https://x/a.html", b"<html>", "text/html")


def test_extract_pdf_text_minimal() -> None:
    data = _minimal_pdf_with_text()
    title, text = extract_pdf_text(data)
    assert "Indonesia" in text
    assert title


def test_fetch_and_extract_pdf_override() -> None:
    data = _minimal_pdf_with_text()
    page = fetch_and_extract(
        "https://static.cninfo.com.cn/finalpage/demo.pdf",
        resolve_dns=False,
        html_override=data,
    )
    assert page.content_kind == "pdf"
    assert page.blob_suffix == ".pdf"
    assert "Indonesia" in page.text
