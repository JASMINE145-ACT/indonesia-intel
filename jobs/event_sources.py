from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventSource, FormalEvent


def event_add_source(
    session: Session, formal_event_id: int, url: str, *, label: str | None = None
) -> EventSource:
    """信息来源 — PRD §5.4。同一事件可挂多来源；按 (event_id, url) 去重。"""
    event = session.get(FormalEvent, formal_event_id)
    if event is None:
        raise KeyError(f"formal_event not found: {formal_event_id}")
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("url is required")

    existing = session.scalar(
        select(EventSource).where(
            EventSource.event_id == formal_event_id, EventSource.url == clean_url
        )
    )
    if existing is not None:
        return existing

    row = EventSource(
        event_id=formal_event_id,
        url=clean_url,
        source_domain=urlparse(clean_url).netloc or None,
        label=label,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def event_list_sources(session: Session, formal_event_id: int) -> list[EventSource]:
    if session.get(FormalEvent, formal_event_id) is None:
        raise KeyError(f"formal_event not found: {formal_event_id}")
    stmt = (
        select(EventSource)
        .where(EventSource.event_id == formal_event_id)
        .order_by(EventSource.created_at)
    )
    return list(session.scalars(stmt))
