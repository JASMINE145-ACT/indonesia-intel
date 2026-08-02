"""PDF text extraction for L1 fetch (disclosure announcements).

Uses pypdf (BSD) — avoids AGPL PyMuPDF for default path.
GitHub precedent: agentladle-mcp-hkexnews / hkex scrapers extract PDF text
after download; we keep extraction inside L1 after httpx GET.
"""
from __future__ import annotations

from io import BytesIO


def extract_pdf_text(data: bytes, *, max_pages: int = 40, max_chars: int = 50_000) -> tuple[str, str]:
    """Return (title_guess, text). Raises ValueError if no extractable text."""
    if not data or len(data) < 5 or not data[:5].startswith(b"%PDF"):
        # Still try — some servers omit magic briefly; pypdf will fail clearly
        pass
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("pypdf not installed; cannot extract PDF") from exc

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — corrupt/empty PDF → ValueError for callers
        raise ValueError(f"pdf_unreadable: {exc}") from exc
    parts: list[str] = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        if t.strip():
            parts.append(t.strip())
    text = "\n\n".join(parts).strip()
    if len(text) < 20:
        raise ValueError("pdf_empty_extraction")
    if len(text) > max_chars:
        text = text[:max_chars]

    title = ""
    meta = getattr(reader, "metadata", None) or {}
    raw_title = None
    if meta:
        raw_title = meta.get("/Title") if hasattr(meta, "get") else getattr(meta, "title", None)
    if raw_title:
        title = str(raw_title).strip()
    if not title:
        # first non-empty line as title guess
        for line in text.splitlines():
            line = line.strip()
            if len(line) >= 8:
                title = line[:200]
                break
    return title, text


def is_pdf_content_type(ctype: str | None) -> bool:
    if not ctype:
        return False
    c = ctype.lower()
    return "application/pdf" in c or c.strip() == "application/octet-stream"


def looks_like_pdf(url: str, data: bytes, ctype: str | None) -> bool:
    if data[:5] == b"%PDF-":
        return True
    if is_pdf_content_type(ctype) and (url.lower().endswith(".pdf") or "pdf" in (ctype or "").lower()):
        return True
    if url.lower().endswith(".pdf") and data[:4] == b"%PDF":
        return True
    return data[:5] == b"%PDF-"
