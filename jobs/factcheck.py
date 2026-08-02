from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Company, FormalEvent, Project, ReviewCandidate
from taxonomy.registry import validate_event_type, validate_industry, validate_project_stage

# 标题/摘要出现左边关键词，但 event_type 记成右边集合内的类型就报警——
# 对应 PRD §9「是否误把入围写成中标 / 签约写成投产」。
_STAGE_WORD_CONFUSIONS: tuple[tuple[str, frozenset[str]], ...] = (
    ("中标", frozenset({"获批运营", "市场表现"})),
    ("签约", frozenset({"投产与运营", "开工建设", "项目建设进展"})),
    ("投产", frozenset({"签约与战略合作", "投资规划与产能布局"})),
)


def factcheck_event(session: Session, formal_event_id: int) -> dict:
    """事实检查面板 — PRD §9。拦截无来源结论、脏引用、常见阶段误写。"""
    event = session.get(FormalEvent, formal_event_id)
    if event is None:
        raise KeyError(f"formal_event not found: {formal_event_id}")

    issues: list[str] = []

    if not event.canonical_url:
        issues.append("缺少可追溯来源链接（canonical_url 为空），禁止用于对外内容生成")

    cand = session.get(ReviewCandidate, event.candidate_id)
    if cand is not None:
        if getattr(cand, "fetch_status", None) == "failed":
            issues.append("抓取失败（fetch_status=failed），禁止用于对外内容生成")
        elif not event.object_key and not (cand.extracted_text or "").strip():
            issues.append("缺少抓取正文（object_key / extracted_text 为空），禁止用于对外内容生成")

    if event.company_id is not None and session.get(Company, event.company_id) is None:
        issues.append(f"company_id={event.company_id} 在企业档案中不存在")
    if event.project_id is not None and session.get(Project, event.project_id) is None:
        issues.append(f"project_id={event.project_id} 在项目档案中不存在")

    if not validate_industry(event.industry):
        issues.append(f"行业分类不在受控词表内: {event.industry}")
    if not validate_event_type(event.event_type):
        issues.append(f"动态类型不在受控词表内: {event.event_type}")
    if not validate_project_stage(event.project_stage):
        issues.append(f"项目阶段不在受控词表内: {event.project_stage}")

    text = f"{event.title or ''} {event.summary or ''}"
    for keyword, conflicting_types in _STAGE_WORD_CONFUSIONS:
        if keyword in text and event.event_type in conflicting_types:
            issues.append(
                f"标题/摘要含“{keyword}”，但动态类型记为“{event.event_type}”，请核实是否写错阶段"
            )

    return {"formal_event_id": formal_event_id, "ok": len(issues) == 0, "issues": issues}
