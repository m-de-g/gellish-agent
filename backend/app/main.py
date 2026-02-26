from __future__ import annotations

from fastapi import FastAPI

from .api import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Gellish Agent API", version="0.1.0")
    app.include_router(api_router)
    return app


app = create_app()
