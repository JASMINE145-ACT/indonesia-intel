from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.fetch import router as fetch_router
from api.intel import router as intel_router
from api.review import router as review_router
from api.search import router as search_router
from app.config import settings
from app.db import init_db
from storage.blob import LocalBlobStore


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="indonesia-intel", version="0.7.0")
    settings.blob_path.mkdir(parents=True, exist_ok=True)
    init_db()
    app.include_router(search_router)
    app.include_router(fetch_router)
    app.include_router(review_router)
    app.include_router(intel_router)

    @app.get("/health")
    def health() -> dict:
        blob = LocalBlobStore(settings.blob_path)
        return {
            "status": "ok",
            "phase": 7,
            "brave_enabled": settings.brave_enabled,
            "exa_configured": bool(settings.exa_api_key),
            "tavily_configured": bool(settings.tavily_api_key),
            "blob_root": str(settings.blob_path),
            "blob_writable": blob.root.exists(),
            "dashboard": "/app/",
        }

    if WEB_DIR.is_dir():
        app.mount("/app", StaticFiles(directory=str(WEB_DIR), html=True), name="app")

    return app


app = create_app()
