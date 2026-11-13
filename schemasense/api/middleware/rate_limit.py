"""Sliding-Window Rate Limiting Middleware for SchemaSense 2.0 API Gateway."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from schemasense.config import get_platform_config
from schemasense.observability.metrics import record_rate_limit_rejection
from schemasense.observability.rate_limiter import get_platform_rate_limiter

logger = logging.getLogger("schemasense.api.ratelimit")

EXEMPT_PATHS = {
    "/health/live",
    "/health/ready",
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/metrics",
    "/api/v1/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforces sliding-window rate limits per client/tenant on API endpoints."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cfg = get_platform_config()
        if not cfg.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        if path in EXEMPT_PATHS:
            return await call_next(request)

        # Derive client identity (authenticated tenant/user or remote client IP)
        client_key = "anonymous"
        auth_header = request.headers.get("Authorization", "")
        tenant_header = request.headers.get("X-Tenant-ID", "")

        if tenant_header.strip():
            client_key = f"tenant:{tenant_header.strip()}"
        elif auth_header.startswith("Bearer "):
            # Use deterministic token slice to bound key length without logging secret
            token_slice = auth_header[7:23]
            client_key = f"bearer:{token_slice}"
        elif request.client and request.client.host:
            client_key = f"ip:{request.client.host}"

        limiter = get_platform_rate_limiter(limit_per_minute=cfg.rate_limit_per_minute)
        is_allowed, remaining, reset_seconds = limiter.check(
            key=f"{client_key}:{path}",
            limit=cfg.rate_limit_per_minute,
        )

        if not is_allowed:
            tenant_id = tenant_header if tenant_header else "anonymous"
            record_rate_limit_rejection(tenant_id=tenant_id, endpoint=path)
            logger.warning(
                "Rate limit exceeded for '%s' on '%s'. Quota reset in %ds",
                client_key,
                path,
                reset_seconds,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Try again in {reset_seconds} seconds."
                },
                headers={
                    "Retry-After": str(reset_seconds),
                    "X-RateLimit-Limit": str(cfg.rate_limit_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_seconds),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(cfg.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_seconds)
        return response
