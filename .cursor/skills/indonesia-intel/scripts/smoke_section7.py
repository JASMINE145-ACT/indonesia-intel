"""Smoke §7 analysis skill contracts (dashboard shape + scope data files).

Run from indonesia-intel package root:

  python .cursor/skills/indonesia-intel/scripts/smoke_section7.py
  python .cursor/skills/indonesia-intel/scripts/smoke_section7.py --skill dashboard

Exit 0 prints OK lines; non-zero on contract break.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Package root = indonesia-intel/
# .../.cursor/skills/indonesia-intel/scripts/smoke_section7.py → parents[4]
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base  # noqa: E402
from app.models import Company, FormalEvent  # noqa: E402
from jobs.stats import dashboard_summary  # noqa: E402

SKILLS = ROOT / ".cursor" / "skills"
DASHBOARD_SCOPE = SKILLS / "indonesia-intel-dashboard" / "data" / "scope.json"
SIGNALS_PROBES = SKILLS / "indonesia-intel-signals" / "data" / "probes.json"

REQUIRED_STATS_KEYS = {
    "filters",
    "industry_distribution",
    "event_type_distribution",
    "project_stage_distribution",
    "monthly_trend",
    "company_ranking",
    "location_distribution",
    "source_distribution",
    "partner_distribution",
    "investment_presence",
    "investment_amount_raw",
    "company_new_vs_existing",
}

SCOPE_IN_SCOPE_STAT_KEYS = {
    "industry_distribution",
    "event_type_distribution",
    "project_stage_distribution",
    "monthly_trend",
    "company_ranking",
    "location_distribution",
    "source_distribution",
    "partner_distribution",
    "investment_presence",
    "investment_amount_raw",
    "company_new_vs_existing",
}


def _session(_db_path: Path | None = None):
    # in-memory avoids Windows sqlite:///C:/… host-parse (WinError 267)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _seed(session) -> None:
    byd = Company(name_cn="比亚迪")
    session.add(byd)
    session.commit()
    session.add_all(
        [
            FormalEvent(
                candidate_id=1,
                title="比亚迪签约",
                canonical_url="https://example.com/1",
                provider="mock",
                company_id=byd.id,
                industry="汽车、工程机械与交通装备",
                event_type="签约与战略合作",
                project_stage="签约",
                occurred_date="2026-05-10",
                is_public=True,
            ),
            FormalEvent(
                candidate_id=2,
                title="比亚迪开工",
                canonical_url="https://example.com/2",
                provider="mock",
                company_id=byd.id,
                industry="汽车、工程机械与交通装备",
                event_type="开工建设",
                project_stage="开工",
                occurred_date="2026-06-01",
                is_public=True,
            ),
        ]
    )
    session.commit()


def smoke_dashboard() -> list[str]:
    lines: list[str] = []
    scope = json.loads(DASHBOARD_SCOPE.read_text(encoding="utf-8"))
    assert "in_scope" in scope and "deferred" in scope, "scope.json missing keys"
    in_scope = set(scope["in_scope"])
    missing_scope = SCOPE_IN_SCOPE_STAT_KEYS - in_scope
    assert not missing_scope, f"scope.json missing stats keys {missing_scope}"
    summary_keys = REQUIRED_STATS_KEYS - {"filters"}
    assert summary_keys <= in_scope, f"summary keys not in scope: {summary_keys - in_scope}"

    session = _session()
    _seed(session)
    summary = dashboard_summary(session, company_limit=10)
    missing = REQUIRED_STATS_KEYS - set(summary)
    assert not missing, f"intel_stats shape missing {missing}"
    for bad in ("investment_numeric_sum", "region_ontology"):
        assert bad not in summary, f"unexpected key {bad}"
    lines.append("OK dashboard: scope.json <-> intel_stats keys")
    return lines


def smoke_nl_analysis() -> list[str]:
    examples = SKILLS / "indonesia-intel-nl-analysis" / "examples.md"
    assert examples.is_file(), "nl-analysis examples.md missing"
    text = examples.read_text(encoding="utf-8")
    for tool in ("intel_stats", "intel_project_list", "intel_factcheck_event"):
        assert tool in text, f"examples.md must mention {tool}"
    session = _session()
    _seed(session)
    a = dashboard_summary(
        session,
        industry="汽车、工程机械与交通装备",
        date_from="2026-01-01",
        date_to="2026-06-30",
    )
    assert a["industry_distribution"], "filtered stats empty unexpectedly"
    return ["OK nl-analysis: examples tools + filtered stats runnable"]


def smoke_compare() -> list[str]:
    examples = SKILLS / "indonesia-intel-compare" / "examples.md"
    assert examples.is_file()
    text = examples.read_text(encoding="utf-8")
    assert "BLOCKED" in text and "SUPPORTED" in text
    session = _session()
    _seed(session)
    a = dashboard_summary(session, date_from="2026-01-01", date_to="2026-06-30")
    b = dashboard_summary(session, date_from="2025-01-01", date_to="2025-06-30")
    assert set(a) == set(b) == REQUIRED_STATS_KEYS
    return ["OK compare: paired intel_stats same keys + examples policy"]


def smoke_signals() -> list[str]:
    probes = json.loads(SIGNALS_PROBES.read_text(encoding="utf-8"))
    types = probes["types"]
    assert len(types) == 7, f"expected 7 PRD types, got {len(types)}"
    ids = {t["id"] for t in types}
    assert ids == set(range(1, 8)), "probe ids must be 1..7"
    examples = SKILLS / "indonesia-intel-signals" / "examples.md"
    assert examples.is_file()
    return ["OK signals: probes.json 7 types + examples.md"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke §7 analysis skill contracts")
    parser.add_argument(
        "--skill",
        choices=["all", "dashboard", "nl-analysis", "compare", "signals"],
        default="all",
    )
    args = parser.parse_args()
    runners = {
        "dashboard": smoke_dashboard,
        "nl-analysis": smoke_nl_analysis,
        "compare": smoke_compare,
        "signals": smoke_signals,
    }
    selected = list(runners) if args.skill == "all" else [args.skill]
    out: list[str] = []
    try:
        for name in selected:
            out.extend(runners[name]())
    except Exception as exc:  # noqa: BLE001 — smoke must print and fail
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    for line in out:
        print(line)
    print("OK smoke_section7")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
