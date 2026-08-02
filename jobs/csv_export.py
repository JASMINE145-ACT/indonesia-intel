from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FormalEvent
from jobs.stats import apply_filters

# PRD §5.2 企业动态字段（子集，跳过内部 object_key/provider 等实现细节）。
EVENT_EXPORT_COLUMNS = [
    "id",
    "title",
    "company_id",
    "project_id",
    "industry",
    "event_type",
    "project_stage",
    "occurred_date",
    "published_date",
    "location",
    "investment_amount",
    "planned_capacity",
    "partners",
    "summary",
    "credibility",
    "is_public",
    "canonical_url",
]


def export_events_csv(session: Session, **filters: Any) -> str:
    """PRD §11.1 数据管理「Excel 导入导出」— CSV 可被 Excel 直接打开/另存为 xlsx。

    只导出（人工审核过的）formal_events；未审核候选不在此列，呼应 PRD §4.3
    "未审核内容不得进入正式分析与公开内容生成"。
    """
    stmt = apply_filters(select(FormalEvent), **filters).order_by(FormalEvent.id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EVENT_EXPORT_COLUMNS)
    for row in session.scalars(stmt):
        writer.writerow([getattr(row, col) for col in EVENT_EXPORT_COLUMNS])
    return buf.getvalue()
