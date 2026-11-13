"""Liveness and Readiness Health Probes for SchemaSense 2.0.

Strictly separates process liveness (/health/live) from capability readiness (/health/ready).
Absence of optional native acceleration core never fails the readiness probe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status

from schemasense.api.schemas import (
    ComponentHealth,
    LivenessResponse,
    ReadinessResponse,
)
from schemasense.config import get_platform_config

logger = logging.getLogger("schemasense.api.health")

router = APIRouter(tags=["Health & Diagnostics"])


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Process Liveness Probe",
)
async def liveness_probe() -> LivenessResponse:
    """Lightweight, non-blocking liveness check.

    Indicates the FastAPI application process is executing and responding.
    Never checks downstream databases, networks, or caches.
    """
    return LivenessResponse(status="alive")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="System Readiness Probe",
)
async def readiness_probe() -> ReadinessResponse:
    """Comprehensive readiness probe evaluating platform subsystem availability.

    Optional acceleration components (like the Rust native core) falling back
    to pure-Python implementations are reported as 'fallback' and do NOT
    fail the readiness status.
    """
    cfg = get_platform_config()
    components: dict[str, ComponentHealth] = {}
    is_ready = True

    # 1. Evaluate Native Rust Core Status
    try:
        from schemasense.schema_inspector import NATIVE_CORE_AVAILABLE

        if NATIVE_CORE_AVAILABLE:
            components["native_core"] = ComponentHealth(
                name="native_core",
                status="available",
                details="PyO3 Rust acceleration core active.",
            )
        else:
            components["native_core"] = ComponentHealth(
                name="native_core",
                status="fallback",
                details="Pure-Python fallback operational (native module absent or disabled).",
            )
    except (ImportError, AttributeError, RuntimeError) as e:
        components["native_core"] = ComponentHealth(
            name="native_core",
            status="fallback",
            details=f"Fallback operational after error: {e}",
        )

    # 2. Evaluate Mode & Infrastructure Readiness
    if cfg.is_simple_mode:
        components["mode_engine"] = ComponentHealth(
            name="mode_engine",
            status="available",
            details="Simple Mode active (zero external daemons).",
        )
    else:
        # Advanced Mode: verify platform database connectivity if configured
        if cfg.platform_db_url:
            try:
                from sqlalchemy import create_engine, text

                engine = create_engine(cfg.platform_db_url, pool_pre_ping=True)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                components["platform_db"] = ComponentHealth(
                    name="platform_db",
                    status="available",
                    details="Platform PostgreSQL pool responsive.",
                )
            except (OSError, RuntimeError) as e:
                logger.error("Platform DB readiness check failed: %s", e)
                components["platform_db"] = ComponentHealth(
                    name="platform_db",
                    status="unavailable",
                    details=f"Database unreachable: {e}",
                )
                is_ready = False
        else:
            components["platform_db"] = ComponentHealth(
                name="platform_db",
                status="disabled",
                details="SCHEMASENSE_PLATFORM_DB_URL not configured.",
            )

        # Redis check in advanced mode if configured
        if cfg.redis_url:
            components["redis_broker"] = ComponentHealth(
                name="redis_broker",
                status="available",
                details="Redis broker URI configured.",
            )

    return ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        mode=cfg.mode,
        components=components,
    )
