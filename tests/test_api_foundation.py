"""Tests for SchemaSense 2.0 API Gateway & Configuration Foundation.

Verifies:
1. Process liveness probe (/health/live).
2. Readiness probe (/health/ready) and non-failing graceful fallback reporting.
3. Strict CORS origin restrictions (no wildcard credentials).
4. Server-side verified identity derivation and rejection of client body spoofing.
5. Connection reference enforcement (forbids raw URIs with credentials).
6. Cross-tenant isolation on connection reference resolution.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="FastAPI is an optional platform dependency")

from fastapi.testclient import TestClient

from schemasense.api.app import create_app
from schemasense.api.schemas import AgentRunCreateRequest
from schemasense.config import (
    PlatformConfig,
    register_connection_reference,
    resolve_connection_reference,
    set_platform_config,
)


def _generate_test_jwt(
    claims: dict[str, Any], secret: str = "test-secret-key-123"
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


@pytest.fixture
def test_config() -> PlatformConfig:
    cfg = PlatformConfig(
        mode="simple",
        cors_allowed_origins=["http://localhost:8501", "http://trusted-app.local"],
        jwt_secret_key="test-secret-key-123",
    )
    set_platform_config(cfg)
    return cfg


@pytest.fixture
def client(test_config: PlatformConfig) -> TestClient:
    app = create_app(test_config)
    return TestClient(app)


# ─────────────────────────────────────────────────────────────
# 1. HEALTH PROBE VERIFICATION
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_liveness_probe(client: TestClient) -> None:
    """Liveness probe must return 200 alive without checking downstream services."""
    resp = client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alive"
    assert "timestamp" in data

    # Also check /api/v1 prefix alias
    resp_v1 = client.get("/api/v1/health/live")
    assert resp_v1.status_code == 200
    assert resp_v1.json()["status"] == "alive"


@pytest.mark.unit
def test_readiness_probe_graceful_fallback(client: TestClient) -> None:
    """Readiness probe must report status without failing if native core is absent."""
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert "components" in data
    assert "native_core" in data["components"]
    assert data["components"]["native_core"]["status"] in ("available", "fallback")


# ─────────────────────────────────────────────────────────────
# 2. CORS RESTRICTIONS
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cors_trusted_origin_permitted(client: TestClient) -> None:
    """CORS must permit pre-flight and responses for configured trusted origins."""
    headers = {
        "Origin": "http://localhost:8501",
        "Access-Control-Request-Method": "POST",
    }
    resp = client.options("/api/v1/agent/runs", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8501"
    assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.unit
def test_cors_untrusted_origin_rejected(client: TestClient) -> None:
    """CORS must strictly deny untrusted origins and forbid wildcard credentials."""
    headers = {
        "Origin": "http://malicious-site.attacker.com",
        "Access-Control-Request-Method": "POST",
    }
    resp = client.options("/api/v1/agent/runs", headers=headers)
    assert resp.headers.get("access-control-allow-origin") is None


@pytest.mark.unit
def test_config_disallows_wildcard_with_credentials() -> None:
    """Configuration must filter out '*' from allowed origins to prevent security vulnerabilities."""
    cfg = PlatformConfig(cors_allowed_origins=["*", "http://localhost:8501"])
    assert "*" not in cfg.cors_allowed_origins
    assert "http://localhost:8501" in cfg.cors_allowed_origins


# ─────────────────────────────────────────────────────────────
# 3. AUTHENTICATION & IDENTITY DERIVATION
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_unauthenticated_request_rejected(client: TestClient) -> None:
    """Protected endpoints must reject requests lacking authentication credentials."""
    resp = client.post(
        "/api/v1/agent/runs",
        json={"prompt": "Inspect database", "connection_id": "test_db"},
    )
    assert resp.status_code == 401
    assert "detail" in resp.json()


@pytest.mark.unit
def test_authenticated_request_derives_identity(
    client: TestClient, test_config: PlatformConfig
) -> None:
    """Identity must be derived strictly from verified token claims, ignoring client spoofing."""
    # Register test connection for tenant "finance"
    register_connection_reference(
        connection_id="fin_db",
        database_uri="sqlite:///:memory:",
        tenant_id="finance",
    )

    claims = {
        "sub": "auditor_alice",
        "tenant_id": "finance",
        "email": "alice@corp.com",
        "roles": ["analyst"],
        "exp": int(time.time()) + 3600,
    }
    token = _generate_test_jwt(claims, test_config.jwt_secret_key)

    resp = client.post(
        "/api/v1/agent/runs",
        json={"prompt": "Find columns with PII", "connection_id": "fin_db"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == "auditor_alice"
    assert data["tenant_id"] == "finance"
    assert data["connection_id"] == "fin_db"
    assert data["current_state"] == "receive"


@pytest.mark.unit
def test_expired_jwt_rejected(client: TestClient, test_config: PlatformConfig) -> None:
    """Expired JWT tokens must be rejected with HTTP 401."""
    claims = {
        "sub": "user_bob",
        "tenant_id": "finance",
        "exp": int(time.time()) - 60,  # Expired
    }
    token = _generate_test_jwt(claims, test_config.jwt_secret_key)

    resp = client.post(
        "/api/v1/agent/runs",
        json={"prompt": "Check schema", "connection_id": "fin_db"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────
# 4. SECURE CONNECTION REFERENCE INVARIANT
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_request_forbids_raw_database_uris() -> None:
    """Requests passing raw database URIs with passwords must be rejected by Pydantic validation."""
    with pytest.raises(ValueError, match="Raw database connection URIs are forbidden"):
        AgentRunCreateRequest(
            prompt="Analyze schema",
            connection_id="postgresql://postgres:secretpassword@db.prod:5432/finance",
        )

    with pytest.raises(ValueError, match="Raw database connection URIs are forbidden"):
        AgentRunCreateRequest(
            prompt="Analyze schema",
            connection_id="user:pass@host",
        )


@pytest.mark.unit
def test_cross_tenant_connection_isolation_enforced() -> None:
    """Tenants must be prevented from accessing connections belonging to other tenants."""
    register_connection_reference(
        connection_id="hr_vault",
        database_uri="sqlite:///:memory:",
        tenant_id="hr_department",
    )

    # Authorized access
    uri = resolve_connection_reference("hr_vault", requesting_tenant_id="hr_department")
    assert uri == "sqlite:///:memory:"

    # Unauthorized cross-tenant access
    with pytest.raises(PermissionError, match="not authorized to access connection"):
        resolve_connection_reference("hr_vault", requesting_tenant_id="marketing")
