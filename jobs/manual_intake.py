from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReviewCandidate
from dedup.url import url_hash
from fetch.pdf import extract_pdf_text
from taxonomy.registry import validate_source_attribution


def _safe_local_pdf_path(path_str: str) -> Path:
    raw = (path_str or "").strip()
    if not raw:
        raise ValueError("path is required")
    # Reject traversal tokens in the user-supplied path before resolve.
    if ".." in Path(raw).parts:
        raise ValueError("path traversal not allowed")
    p = Path(raw).expanduser().resolve(strict=False)
    if not p.is_file():
        raise ValueError(f"path is not a file: {p}")
    if p.suffix.lower() != ".pdf":
        raise ValueError("path must end with .pdf")
    return p


def manual_add_candidate(
    session: Session,
    *,
    title: str,
    url: str = "",
    text: str = "",
    source_attribution: str = "待验证",
    is_public_source: bool = True,
) -> ReviewCandidate:
    """人工投喂 — PRD §4.4：网页链接 / 粘贴文字 / 手工创建事件（无公开链接）统一落到
    待审核池，跳过自动发现，直接进入 pending_review（人仍需走 confirm/ignore）。

    来源属性 + 是否可对外使用在此登记，confirm 时若未显式传 is_public 会沿用这里
    的标记，避免非公开信息被漏标后误入公开内容生成。
    """
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("title is required")
    if not (url or "").strip() and not (text or "").strip():
        raise ValueError("url or text is required")
    if not validate_source_attribution(source_attribution):
        raise ValueError(f"source_attribution not in controlled taxonomy: {source_attribution}")

    raw_url = (url or "").strip()
    if raw_url:
        existing = session.scalar(
            select(ReviewCandidate).where(ReviewCandidate.url_hash == url_hash(raw_url))
        )
        if existing is not None:
            return existing
    canonical = raw_url or f"manual://{uuid.uuid4().hex}"

    now = datetime.now(timezone.utc)
    row = ReviewCandidate(
        run_id=f"manual-{uuid.uuid4().hex[:12]}",
        provider="manual",
        query="",
        original_url=raw_url or canonical,
        canonical_url=canonical,
        url_hash=url_hash(canonical),
        title=clean_title,
        snippet=(text or "")[:280],
        extracted_text=text or None,
        status="pending_review",
        fetch_status="ok" if (text or "").strip() else "not_attempted",
        source_attribution=source_attribution,
        is_public_source=is_public_source,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def manual_add_pdf(
    session: Session,
    path: str,
    *,
    source_attribution: str = "待验证",
    is_public_source: bool = True,
    title: str = "",
) -> ReviewCandidate:
    """本地 PDF → 抽文本 → pending_review（PRD §4.4 文件投喂子集）。"""
    if not validate_source_attribution(source_attribution):
        raise ValueError(f"source_attribution not in controlled taxonomy: {source_attribution}")

    pdf_path = _safe_local_pdf_path(path)
    data = pdf_path.read_bytes()
    title_guess, text = extract_pdf_text(data)
    clean_title = (title or "").strip() or title_guess or pdf_path.stem
    if not clean_title:
        raise ValueError("title could not be derived from PDF")

    canonical = f"manual-pdf://{pdf_path.resolve().as_posix()}"
    existing = session.scalar(
        select(ReviewCandidate).where(ReviewCandidate.url_hash == url_hash(canonical))
    )
    if existing is not None:
        return existing

    now = datetime.now(timezone.utc)
    row = ReviewCandidate(
        run_id=f"manual-pdf-{uuid.uuid4().hex[:12]}",
        provider="manual_pdf",
        query="",
        original_url=str(pdf_path),
        canonical_url=canonical,
        url_hash=url_hash(canonical),
        title=clean_title[:1024],
        snippet=text[:280],
        extracted_text=text,
        status="pending_review",
        source_attribution=source_attribution,
        is_public_source=is_public_source,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
