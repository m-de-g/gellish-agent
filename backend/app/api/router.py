from __future__ import annotations

from fastapi import APIRouter

from .routes.documents import router as documents_router
from .routes.health import router as health_router
from .routes.translate import router as translate_router

router = APIRouter()
router.include_router(health_router)
router.include_router(documents_router)
router.include_router(translate_router)
