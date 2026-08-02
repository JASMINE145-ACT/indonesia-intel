from __future__ import annotations

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings


def get_db():
    from app import db as dbmod

    db = dbmod.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return x_api_key
