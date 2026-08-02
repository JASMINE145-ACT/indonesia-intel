from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.schema import CreateColumn

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _add_missing_columns(bind: Engine) -> None:
    """No Alembic in this project (Phase-1 scaffold) — `create_all` only creates
    missing *tables*, it never alters an existing one. Without this, adding a
    field to an existing model (as this session's PRD §5 work did to
    `formal_events`) would silently desync from anyone's already-populated
    `data/intel.db` and start raising `OperationalError: no such column`.
    SQLite-only: purely additive (ADD COLUMN), never drops/renames anything.
    """
    if bind.dialect.name != "sqlite":
        return
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {
                row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')
            }
            if not existing:
                continue  # table itself doesn't exist yet — create_all's job
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = CreateColumn(col).compile(dialect=conn.dialect)
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}')


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _add_missing_columns(engine)
