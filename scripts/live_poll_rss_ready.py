"""Live smoke: poll each rss_ready feed once (network)."""
from __future__ import annotations

import json
from pathlib import Path

from app.db import Base
from jobs.poll_rss import poll_rss_source
from sources.store import load_merged
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def main() -> int:
    db = Path(__file__).resolve().parents[1] / "data" / "rss-smoke.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    reg = load_merged()
    ready = reg.rss_ready()
    rows = []
    with Session() as session:
        for src in ready:
            try:
                out = poll_rss_source(session, src, limit=10)
                rows.append(
                    {
                        "id": src.id,
                        "ok": "error" not in out and not out.get("skipped"),
                        "hits": out.get("hits"),
                        "inserted": out.get("inserted"),
                        "error": out.get("error") or out.get("reason"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                rows.append({"id": src.id, "ok": False, "error": str(exc)[:200]})
            print(json.dumps(rows[-1], ensure_ascii=False))

    path = Path(__file__).resolve().parents[1] / "evidence" / "rss-live-poll-20260731.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in rows if r.get("ok"))
    print(f"live_ok={ok}/{len(rows)} -> {path}")
    return 0 if ok >= 6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
