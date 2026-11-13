"""API Routes Registry for SchemaSense 2.0."""

from __future__ import annotations

from fastapi import APIRouter

from schemasense.api.routes.agent import router as agent_router
from schemasense.api.routes.health import router as health_router

router = APIRouter()

# Mount health & diagnostic probes
router.include_router(health_router)

# Mount agent orchestration routes
router.include_router(agent_router)
