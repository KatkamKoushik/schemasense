"""FastAPI Application Gateway Factory for SchemaSense 2.0.

Provides authenticated API routing, strict CORS origin validation,
separated liveness/readiness probes, and security header enforcement.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from schemasense.api.middleware.observability import ObservabilityMiddleware
from schemasense.api.middleware.rate_limit import RateLimitMiddleware
from schemasense.api.routes import router as api_v1_router
from schemasense.api.routes.health import router as health_router
from schemasense.api.routes.metrics import router as metrics_router
from schemasense.config import PlatformConfig, get_platform_config, set_platform_config

logger = logging.getLogger("schemasense.api")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces standard defensive HTTP security headers on all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


@asynccontextmanager
async def platform_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan event handler for application bootstrap and graceful teardown."""
    cfg = get_platform_config()
    logger.info(
        "Starting SchemaSense 2.0 API Gateway [Mode: %s]",
        cfg.mode.upper(),
    )
    yield
    logger.info("Shutting down SchemaSense 2.0 API Gateway.")


def create_app(config: PlatformConfig | None = None) -> FastAPI:
    """Builds and configures the FastAPI application instance."""
    if config is not None:
        set_platform_config(config)

    cfg = get_platform_config()

    app = FastAPI(
        title="SchemaSense 2.0 Platform API",
        version="2.0.0",
        description="AI-native database intelligence, schema governance, and agent orchestration platform.",
        lifespan=platform_lifespan,
    )

    # 1. Enforce Defensive Security Headers
    app.add_middleware(SecurityHeadersMiddleware)

    # 2. Strict CORS with Explicitly Configured Trusted Origins (No Wildcard Credentials)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
    )

    # 3. Observability & Distributed Tracing Middleware
    app.add_middleware(ObservabilityMiddleware)

    # 4. Sliding-Window Rate Limiting Middleware
    app.add_middleware(RateLimitMiddleware)

    # 5. Mount Probes and Metrics at Root and /api/v1
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


# Default application instance for ASGI servers (Uvicorn / Gunicorn)
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("schemasense.api.app:app", host="0.0.0.0", port=8000)
