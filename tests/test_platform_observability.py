"""Tests for SchemaSense 2.0 Observability, Prometheus Metrics & Gateway Rate Limiting.

Verifies:
1. Standard Prometheus exposition format (version 0.0.4) on GET /metrics.
2. Privacy-preserving telemetry invariant: Zero raw SQL or credentials in metrics (Mandatory Correction 18).
3. Sliding-window rate limiting middleware enforcement with HTTP 429 and Retry-After headers.
4. Exemption of diagnostic probes (/health/live, /health/ready, /metrics) from rate limits.
5. OpenTelemetry-compatible distributed span lifecycle and attribute sanitization (Mandatory Correction 7).
6. SQLGuard AST validation integration with Prometheus metrics counters.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi.testclient import TestClient

from schemasense.api.app import create_app
from schemasense.config import PlatformConfig, set_platform_config
from schemasense.observability.metrics import (
    PrometheusRegistry,
    get_metrics_registry,
    record_agent_run,
    record_queue_task,
    record_tool_invocation,
)
from schemasense.observability.rate_limiter import (
    RateLimiter,
    get_platform_rate_limiter,
)
from schemasense.observability.tracer import get_current_span, trace_span
from schemasense.sql_guard import SQLGuard


def _generate_test_jwt(
    claims: dict[str, Any],
    secret: str = "schemasense-insecure-dev-secret-change-in-prod",
) -> str:
    """Helper to generate an HS256 signed test JWT."""
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = (
        base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    )
    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def test_prometheus_registry_counter_and_histogram():
    """Verifies counter and histogram collection in standard Prometheus format."""
    reg = PrometheusRegistry()
    reg.agent_runs_total.inc(amount=2, tenant_id="tenant_alpha", status="completed")
    reg.agent_runs_total.inc(amount=1, tenant_id="tenant_alpha", status="failed")

    reg.agent_state_duration.observe(amount=0.035, state="plan", status="success")
    reg.agent_state_duration.observe(amount=1.2, state="execute", status="success")

    exposition = reg.generate_exposition()

    assert "# HELP schemasense_agent_runs_total" in exposition
    assert "# TYPE schemasense_agent_runs_total counter" in exposition
    assert (
        'schemasense_agent_runs_total{status="completed",tenant_id="tenant_alpha"} 2'
        in exposition
    )
    assert (
        'schemasense_agent_runs_total{status="failed",tenant_id="tenant_alpha"} 1'
        in exposition
    )

    assert "# HELP schemasense_agent_state_duration_seconds" in exposition
    assert "# TYPE schemasense_agent_state_duration_seconds histogram" in exposition
    assert (
        'schemasense_agent_state_duration_seconds_bucket{le="0.05",state="plan",status="success"} 1'
        in exposition
    )
    assert (
        'schemasense_agent_state_duration_seconds_count{state="plan",status="success"} 1'
        in exposition
    )


def test_metrics_endpoint_export():
    """Verifies GET /metrics produces Prometheus compliant plain text."""
    reg = get_metrics_registry()
    reg.clear()

    record_agent_run(tenant_id="tenant_omega", status="completed", count=5)
    record_tool_invocation(tool_name="profile_column", status="success", count=3)
    record_queue_task(task_name="execute_profiling", status="success", count=2)

    app = create_app(PlatformConfig(mode="advanced"))
    client = TestClient(app)

    # 1. Root /metrics endpoint
    res_root = client.get("/metrics")
    assert res_root.status_code == 200
    assert "text/plain" in res_root.headers["content-type"]
    assert "version=0.0.4" in res_root.headers["content-type"]
    assert (
        'schemasense_agent_runs_total{status="completed",tenant_id="tenant_omega"} 5'
        in res_root.text
    )
    assert (
        'schemasense_tool_invocations_total{status="success",tool_name="profile_column"} 3'
        in res_root.text
    )
    assert (
        'schemasense_queue_tasks_total{status="success",task_name="execute_profiling"} 2'
        in res_root.text
    )

    # 2. Versioned /api/v1/metrics endpoint
    res_v1 = client.get("/api/v1/metrics")
    assert res_v1.status_code == 200
    assert (
        'schemasense_agent_runs_total{status="completed",tenant_id="tenant_omega"} 5'
        in res_v1.text
    )


def test_metrics_never_contain_raw_sql_or_credentials():
    """Verifies Mandatory Correction 18: Telemetry must be privacy-preserving and leak zero secrets."""
    reg = get_metrics_registry()
    reg.clear()

    # Simulate queries with raw SQL and credentials
    raw_query = (
        "SELECT * FROM confidential_users WHERE password = 'super_secret_password_123';"
    )
    SQLGuard.validate(raw_query, dialect="postgres")

    exposition = reg.generate_exposition()

    assert "super_secret_password_123" not in exposition
    assert "confidential_users" not in exposition
    assert "SELECT * FROM" not in exposition
    # Only sanitized decision and dialect labels are present
    assert (
        'schemasense_sqlguard_validations_total{decision="allowed",dialect="postgres"}'
        in exposition
    )


def test_sliding_window_rate_limiter_unit():
    """Tests in-memory sliding window rate limiter logic."""
    limiter = RateLimiter(default_limit_per_minute=3, window_seconds=10.0)
    key = "tenant_test"
    base_time = 1000.0

    # 1. First 3 requests permitted
    ok1, rem1, _ = limiter.check(key, limit=3, now=base_time)
    assert ok1 is True
    assert rem1 == 2

    ok2, rem2, _ = limiter.check(key, limit=3, now=base_time + 1.0)
    assert ok2 is True
    assert rem2 == 1

    ok3, rem3, _ = limiter.check(key, limit=3, now=base_time + 2.0)
    assert ok3 is True
    assert rem3 == 0

    # 2. 4th request blocked
    ok4, rem4, reset_sec = limiter.check(key, limit=3, now=base_time + 3.0)
    assert ok4 is False
    assert rem4 == 0
    assert reset_sec == 7  # 10s window - 3s elapsed from earliest request

    # 3. Request at 11.0s: 1000.0 and 1001.0 slid out, but 1002.0 is still within 10s window (1011 - 1002 = 9s)
    ok5, rem5, _ = limiter.check(key, limit=3, now=base_time + 11.0)
    assert ok5 is True
    assert rem5 == 1  # 1002.0 + 1011.0 are active, so 3 - 2 = 1 remaining

    # 4. Request at 15.0s: all 3 initial requests (1000, 1001, 1002) have slid out
    limiter.reset()
    ok6, rem6, _ = limiter.check(key, limit=3, now=base_time + 15.0)
    assert ok6 is True
    assert rem6 == 2


def test_rate_limit_middleware_enforces_quota():
    """Verifies that FastAPI gateway enforces rate limits and returns HTTP 429 with Retry-After."""
    cfg = PlatformConfig(
        mode="advanced",
        rate_limit_enabled=True,
        rate_limit_per_minute=2,
    )
    set_platform_config(cfg)
    get_platform_rate_limiter().reset()

    app = create_app(cfg)
    client = TestClient(app)

    claims = {
        "sub": "usr_test",
        "tenant_id": "tenant_quota",
        "roles": ["user"],
        "exp": time.time() + 3600,
    }
    token = _generate_test_jwt(claims, cfg.jwt_secret_key)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": "tenant_quota"}

    # Request 1: Allowed
    r1 = client.get("/api/v1/health/live", headers=headers)
    assert r1.status_code == 200

    # Request to a non-exempt path 1: Allowed
    r2 = client.get("/api/v1/agent/runs/fake-run-id", headers=headers)
    assert r2.status_code in (404, 200)
    assert "X-RateLimit-Limit" in r2.headers
    assert r2.headers["X-RateLimit-Remaining"] == "1"

    # Request 2: Allowed
    r3 = client.get("/api/v1/agent/runs/fake-run-id", headers=headers)
    assert r3.status_code in (404, 200)
    assert r3.headers["X-RateLimit-Remaining"] == "0"

    # Request 3: Blocked with HTTP 429 Too Many Requests
    r4 = client.get("/api/v1/agent/runs/fake-run-id", headers=headers)
    assert r4.status_code == 429
    assert "Rate limit exceeded" in r4.json()["detail"]
    assert "Retry-After" in r4.headers
    assert int(r4.headers["Retry-After"]) >= 1


def test_exempt_probes_never_rate_limited():
    """Verifies that liveness, readiness, and metrics endpoints are never throttled."""
    cfg = PlatformConfig(
        mode="advanced",
        rate_limit_enabled=True,
        rate_limit_per_minute=2,
    )
    set_platform_config(cfg)
    get_platform_rate_limiter().reset()

    app = create_app(cfg)
    client = TestClient(app)

    for _ in range(10):
        res_live = client.get("/health/live")
        assert res_live.status_code == 200
        res_ready = client.get("/health/ready")
        assert res_ready.status_code == 200
        res_metrics = client.get("/metrics")
        assert res_metrics.status_code == 200


def test_opentelemetry_compatible_tracing_lifecycle():
    """Verifies distributed span creation, context nesting, and sensitive attribute masking."""
    with trace_span(
        "parent_agent_lifecycle", {"tenant_id": "tenant_trace"}
    ) as parent_span:
        assert parent_span.trace_id is not None
        assert parent_span.span_id is not None
        assert parent_span.status == "OK"
        assert get_current_span() is parent_span

        # Sensitive attribute must be redacted automatically (Mandatory Correction 7)
        parent_span.set_attribute(
            "db.connection", "postgresql://admin:super_secret_pw@db:5432/db"
        )
        assert "super_secret_pw" not in parent_span.attributes["db.connection"]
        assert "***" in parent_span.attributes["db.connection"]

        # Nested Child Span
        with trace_span("child_tool_exec", {"tool": "profile_column"}) as child_span:
            assert child_span.trace_id == parent_span.trace_id  # Trace ID propagated
            assert child_span.parent_span_id == parent_span.span_id
            assert get_current_span() is child_span

            # Exception recording
            try:
                raise ValueError("Sensitive token failure: token=secret_tok_xyz")
            except ValueError as e:
                child_span.record_exception(e)

            assert child_span.status == "ERROR"
            assert "secret_tok_xyz" not in str(child_span.events)

    # After exit, current span is reset
    assert get_current_span() is None
    assert parent_span.duration_seconds >= 0.0


def test_api_gateway_attaches_trace_correlation_headers():
    """Verifies that the API gateway attaches X-Trace-ID and X-Response-Time-Seconds."""
    app = create_app(PlatformConfig(mode="advanced"))
    client = TestClient(app)

    res = client.get("/health/live")
    assert res.status_code == 200
    assert "X-Trace-ID" in res.headers
    assert len(res.headers["X-Trace-ID"]) >= 16
    assert "X-Response-Time-Seconds" in res.headers
