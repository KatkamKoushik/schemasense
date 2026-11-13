"""SchemaSense 2.0 Configuration Management.

Enforces strict separation between Simple Mode (zero external daemons) and
Advanced Mode (enterprise platform), with secure connection references,
trusted CORS origin controls, and authenticated context derivation.
"""

from __future__ import annotations

import logging
import os
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger("schemasense.config")

# Deployment Modes
DeploymentMode = Literal["simple", "advanced"]


class PlatformConfig:
    """Immutable, validated configuration for SchemaSense 2.0."""

    def __init__(
        self,
        mode: DeploymentMode | None = None,
        cors_allowed_origins: list[str] | None = None,
        jwt_secret_key: str | None = None,
        jwt_algorithm: str = "HS256",
        platform_db_url: str | None = None,
        redis_url: str | None = None,
    ) -> None:
        mode_str = mode or os.getenv("SCHEMASENSE_MODE") or "simple"
        raw_mode = mode_str.strip().lower()

        if raw_mode not in ("simple", "advanced"):
            logger.warning(
                "Unrecognized SCHEMASENSE_MODE '%s'; defaulting to 'simple'",
                raw_mode,
            )
            raw_mode = "simple"

        self.mode: DeploymentMode = "advanced" if raw_mode == "advanced" else "simple"

        # CORS: Strictly configurable trusted origins, disallowing wildcard with credentials
        raw_env_origins = os.getenv(
            "SCHEMASENSE_CORS_ORIGINS",
            "http://localhost:8501,http://127.0.0.1:8501,http://localhost:3000",
        )
        raw_origins = (
            cors_allowed_origins
            if cors_allowed_origins is not None
            else raw_env_origins.split(",")
        )
        cleaned_origins = [origin.strip() for origin in raw_origins if origin.strip()]
        # Never allow wildcard when authenticated requests are served
        self.cors_allowed_origins: list[str] = [o for o in cleaned_origins if o != "*"]
        if not self.cors_allowed_origins:
            self.cors_allowed_origins = [
                "http://localhost:8501",
                "http://127.0.0.1:8501",
            ]

        # JWT / OIDC Configuration
        resolved_secret = (
            jwt_secret_key
            or os.getenv("SCHEMASENSE_JWT_SECRET")
            or "schemasense-insecure-dev-secret-change-in-prod"
        )
        self.jwt_secret_key: str = resolved_secret
        self.jwt_algorithm: str = jwt_algorithm

        # Advanced Mode Infrastructure (None in Simple Mode)
        self.platform_db_url: str | None = platform_db_url or os.getenv(
            "SCHEMASENSE_PLATFORM_DB_URL"
        )
        self.redis_url: str | None = redis_url or os.getenv("REDIS_URL")
        self.celery_broker_url: str | None = (
            os.getenv("CELERY_BROKER_URL") or self.redis_url
        )
        self.celery_result_backend: str | None = (
            os.getenv("CELERY_RESULT_BACKEND") or self.redis_url
        )

    @property
    def is_advanced_mode(self) -> bool:
        return self.mode == "advanced"

    @property
    def is_simple_mode(self) -> bool:
        return self.mode == "simple"


# Global Default Config
_CURRENT_CONFIG: PlatformConfig | None = None


def get_platform_config() -> PlatformConfig:
    """Retrieves or initializes the active platform configuration."""
    global _CURRENT_CONFIG
    if _CURRENT_CONFIG is None:
        _CURRENT_CONFIG = PlatformConfig()
    return _CURRENT_CONFIG


def set_platform_config(config: PlatformConfig | None) -> None:
    """Overrides the active platform configuration (primarily for testing)."""
    global _CURRENT_CONFIG
    _CURRENT_CONFIG = config


# ─────────────────────────────────────────────────────────────
# SECURE CONNECTION REFERENCE REGISTRY
# Avoids persisting or passing raw credentials / database URIs
# ─────────────────────────────────────────────────────────────

_CONNECTION_REGISTRY: dict[str, dict[str, str]] = {}


def clear_connection_references() -> None:
    """Clears all registered connection references (used for test isolation)."""
    _CONNECTION_REGISTRY.clear()


def register_connection_reference(
    connection_id: str,
    database_uri: str,
    name: str = "",
    tenant_id: str = "default",
) -> str:
    """Registers a database URI under a secure, server-side connection reference ID.

    The client and state machines only ever see and pass `connection_id`.
    """
    clean_id = connection_id.strip()
    if not clean_id:
        raise ValueError("connection_id must not be empty.")

    _CONNECTION_REGISTRY[clean_id] = {
        "uri": database_uri,
        "name": name or clean_id,
        "tenant_id": tenant_id,
    }
    return clean_id


def resolve_connection_reference(
    connection_id: str,
    requesting_tenant_id: str = "default",
) -> str:
    """Resolves a connection_id to its actual database URI, enforcing tenant isolation.

    Raises:
        KeyError: If connection_id does not exist.
        PermissionError: If tenant does not own the connection.
    """
    clean_id = connection_id.strip()
    if clean_id not in _CONNECTION_REGISTRY:
        raise KeyError(f"Connection reference '{clean_id}' not found.")

    entry = _CONNECTION_REGISTRY[clean_id]
    if entry["tenant_id"] != requesting_tenant_id and entry["tenant_id"] != "*":
        logger.warning(
            "Tenant '%s' attempted to access connection '%s' owned by '%s'",
            requesting_tenant_id,
            clean_id,
            entry["tenant_id"],
        )
        raise PermissionError(
            f"Tenant '{requesting_tenant_id}' is not authorized to access connection '{clean_id}'."
        )

    return entry["uri"]


def sanitize_uri_for_display(database_uri: str) -> str:
    """Redacts credentials from a database URI for safe display/logging."""
    try:
        parsed = urlparse(database_uri)
        if parsed.password:
            netloc = f"{parsed.username or ''}:***@{parsed.hostname or ''}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
        return database_uri
    except (ValueError, TypeError, AttributeError):
        return "<sanitized_uri>"
