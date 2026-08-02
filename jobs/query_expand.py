"""Query expansion for search ingest — WANd.INTEL.QUERY_EXPAND.001."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

# Lightweight CN→EN aliases for common China→Indonesia entities (no LLM).
_ENTITY_ALIASES: dict[str, str] = {
    "比亚迪": "BYD",
    "宁德时代": "CATL",
    "华为": "Huawei",
    "阿里巴巴": "Alibaba",
    "腾讯": "Tencent",
    "小米": "Xiaomi",
    "山海图": "Shanhaitu",
}


def expand_queries(
    query: str,
    session: Session | None = None,
    *,
    enabled: bool = True,
    max_variants: int = 4,
) -> list[str]:
    """Return deduped query variants (original first), capped at max_variants."""
    q = (query or "").strip()
    if not q:
        return []
    if not enabled:
        return [q]

    out: list[str] = []
    seen: set[str] = set()

    def _add(s: str) -> None:
        s = (s or "").strip()
        if not s or s in seen or len(out) >= max_variants:
            return
        seen.add(s)
        out.append(s)

    _add(q)

    company_hit = False
    if session is not None:
        from app.models import Company

        clauses = [Company.name_cn.contains(q)]
        if hasattr(Company, "brand"):
            clauses.append(Company.brand.contains(q))
        rows = list(session.scalars(select(Company).where(or_(*clauses)).limit(5)))
        if not rows:
            # Fallback: query token appears inside a stored name (or vice versa)
            for c in session.scalars(select(Company).limit(500)):
                name = c.name_cn or ""
                brand = c.brand or ""
                if q in name or name in q or (brand and (q in brand or brand in q)):
                    rows.append(c)
                if len(rows) >= 3:
                    break
        for c in rows:
            company_hit = True
            if c.name_en:
                _add(f"{c.name_en} Indonesia")
            if c.name_id:
                _add(c.name_id)

    if not company_hit:
        for cn, en in _ENTITY_ALIASES.items():
            if cn in q:
                _add(q.replace(cn, en))
                _add(f"{en} Indonesia")
                break
        _add(f"{q} Indonesia")
        _add(f"{q} investasi OR pabrik OR proyek")

    return out[:max_variants]
