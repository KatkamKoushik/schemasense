"""Unit and contract tests for SchemaSense 2.0 Platform Deployment & Docker Orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi", reason="FastAPI is an optional platform dependency")

from schemasense.api.app import app
from schemasense.config import PlatformConfig


@pytest.fixture
def repo_root() -> Path:
    """Returns the repository root directory."""
    return Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_dockerfile_structure_and_hardening(repo_root: Path) -> None:
    """Verifies Dockerfile exists, uses multi-stage builds, and enforces unprivileged user execution."""
    dockerfile_path = repo_root / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at repository root"

    content = dockerfile_path.read_text(encoding="utf-8")

    # Multi-stage build verification
    assert "AS rust-builder" in content, "Must include native Rust builder stage"
    assert "AS runtime" in content, "Must include production runtime stage"

    # Security hardening verification
    assert "useradd -u 10001" in content, "Must create unprivileged user"
    assert "USER schemasense" in content, (
        "Must execute container under unprivileged user"
    )
    assert "HEALTHCHECK" in content, "Must declare container HEALTHCHECK probe"


@pytest.mark.unit
def test_docker_compose_specification(repo_root: Path) -> None:
    """Verifies docker-compose.yml defines all 6 SchemaSense 2.0 platform services with healthchecks."""
    compose_path = repo_root / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist at repository root"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    assert "services" in compose_data, "docker-compose.yml must define services"
    services = compose_data["services"]

    # Verify all 6 mandatory platform services are declared
    expected_services = [
        "schemasense-db",
        "schemasense-redis",
        "schemasense-migration",
        "schemasense-api",
        "schemasense-worker",
        "schemasense-ui",
    ]
    for s_name in expected_services:
        assert s_name in services, (
            f"Service '{s_name}' must be declared in docker-compose.yml"
        )

    # Mandatory Correction 1: Migration must run explicitly, not during API boot
    migration_svc = services["schemasense-migration"]
    assert "schemasense.db.migrate" in " ".join(migration_svc["command"])

    # Healthcheck verification
    assert "healthcheck" in services["schemasense-db"]
    assert "healthcheck" in services["schemasense-redis"]
    assert "healthcheck" in services["schemasense-api"]
    assert "healthcheck" in services["schemasense-ui"]

    # Port mappings verification
    assert any("8000" in p for p in services["schemasense-api"]["ports"])
    assert any("8501" in p for p in services["schemasense-ui"]["ports"])


@pytest.mark.unit
def test_fastapi_app_instance_and_routes() -> None:
    """Verifies top-level ASGI app object exists and includes health and agent routers."""
    assert app is not None
    assert app.title == "SchemaSense 2.0 Platform API"

    openapi_paths = list(app.openapi()["paths"].keys())

    # Health probes
    assert "/health/live" in openapi_paths
    assert "/health/ready" in openapi_paths

    # Agent orchestration endpoints
    assert "/api/v1/agent/runs" in openapi_paths
    assert "/api/v1/agent/runs/{run_id}" in openapi_paths
    assert "/api/v1/agent/runs/{run_id}/approval" in openapi_paths
    assert "/api/v1/agent/runs/{run_id}/events" in openapi_paths
    assert "/api/v1/agent/profiling" in openapi_paths


@pytest.mark.unit
def test_platform_config_mode_switching() -> None:
    """Verifies PlatformConfig correctly distinguishes Simple and Advanced modes."""
    simple_cfg = PlatformConfig(mode="simple")
    assert simple_cfg.is_simple_mode is True
    assert simple_cfg.is_advanced_mode is False

    adv_cfg = PlatformConfig(mode="advanced")
    assert adv_cfg.is_simple_mode is False
    assert adv_cfg.is_advanced_mode is True
