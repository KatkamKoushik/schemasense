"""Observability & Distributed Tracing Middleware for SchemaSense 2.0 API Gateway."""

from __future__ import annotations

import re
import time
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from schemasense.config import get_platform_config
from schemasense.observability.metrics import record_http_request
from schemasense.observability.tracer import trace_span

# Regex to normalize UUIDs and hexadecimal identifiers to prevent Prometheus label cardinality explosion
_UUID_OR_HEX_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{16,64}\b",
    re.IGNORECASE,
)


def normalize_route_path(path: str) -> str:
    """Replaces dynamic IDs in path with '{id}' to bound metric cardinality."""
    return _UUID_OR_HEX_RE.sub("{id}", path)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Measures HTTP request latency, records Prometheus metrics, and traces spans."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cfg = get_platform_config()
        t0 = time.perf_counter()
        raw_path = request.url.path
        method = request.method
        normalized_path = normalize_route_path(raw_path)

        with trace_span(
            f"HTTP {method} {normalized_path}",
            {
                "http.method": method,
                "http.route": normalized_path,
                "http.url": str(request.url),
                "client.address": request.client.host if request.client else "unknown",
            },
        ) as span:
            try:
                response = await call_next(request)
                duration = time.perf_counter() - t0

                if cfg.telemetry_enabled:
                    record_http_request(
                        endpoint=normalized_path,
                        method=method,
                        status_code=response.status_code,
                        duration_seconds=duration,
                    )

                span.set_attribute("http.status_code", response.status_code)
                span.set_attribute("http.duration_seconds", round(duration, 4))
                if response.status_code >= 400:
                    span.set_status("ERROR")

                # Attach correlation headers
                response.headers["X-Trace-ID"] = span.trace_id
                response.headers["X-Response-Time-Seconds"] = f"{duration:.4f}"
                return response

            except Exception as exc:
                duration = time.perf_counter() - t0
                if cfg.telemetry_enabled:
                    record_http_request(
                        endpoint=normalized_path,
                        method=method,
                        status_code=500,
                        duration_seconds=duration,
                    )
                span.record_exception(exc)
                span.set_status("ERROR")
                raise
