"""SchemaSense 2.0 Observability, Metrics & Security Guardrails.

Provides zero-dependency Prometheus metrics exposition, OpenTelemetry-compatible
distributed tracing, and sliding-window rate limiting.
"""

from __future__ import annotations

from schemasense.observability.metrics import (
    PrometheusRegistry,
    get_metrics_registry,
    record_agent_run,
    record_agent_state_duration,
    record_http_request,
    record_queue_task,
    record_rate_limit_rejection,
    record_sqlguard_validation,
    record_tool_invocation,
)
from schemasense.observability.rate_limiter import (
    RateLimiter,
    get_platform_rate_limiter,
)
from schemasense.observability.tracer import (
    Span,
    get_current_span,
    get_tracer,
    trace_span,
)

__all__ = [
    "PrometheusRegistry",
    "get_metrics_registry",
    "record_agent_run",
    "record_agent_state_duration",
    "record_http_request",
    "record_queue_task",
    "record_rate_limit_rejection",
    "record_sqlguard_validation",
    "record_tool_invocation",
    "RateLimiter",
    "get_platform_rate_limiter",
    "Span",
    "get_current_span",
    "get_tracer",
    "trace_span",
]
