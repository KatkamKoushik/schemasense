"""Pydantic V2 Schemas for SchemaSense 2.0 API Gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ─────────────────────────────────────────────────────────────
# HEALTH & OBSERVABILITY SCHEMAS
# ─────────────────────────────────────────────────────────────


class LivenessResponse(BaseModel):
    """Liveness probe indicating the process is executing."""

    status: str = "alive"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ComponentHealth(BaseModel):
    """Health indicator for an individual subsystem or accelerator."""

    name: str
    status: Literal["available", "fallback", "degraded", "unavailable", "disabled"]
    details: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness probe indicating if the service can accept user requests."""

    status: Literal["ready", "not_ready"]
    mode: Literal["simple", "advanced"]
    components: dict[str, ComponentHealth]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ─────────────────────────────────────────────────────────────
# IDENTITY & AUTHENTICATION CONTEXT
# ─────────────────────────────────────────────────────────────


class AuthenticatedIdentity(BaseModel):
    """Cryptographically derived, server-verified user and tenant identity."""

    user_id: str
    tenant_id: str = "default"
    email: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["user"])
    auth_method: str = "token"

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


# ─────────────────────────────────────────────────────────────
# AGENT REQUEST & RESPONSE SCHEMAS
# ─────────────────────────────────────────────────────────────


class AgentRunCreateRequest(BaseModel):
    """Request to initiate an agent analytical or inspection run."""

    prompt: str = Field(
        min_length=1,
        max_length=4000,
        description="Natural language instruction for the SchemaSense agent.",
    )
    connection_id: str = Field(
        description=(
            "Secure, server-side registered reference ID for the target database. "
            "Raw database URIs or passwords are strictly forbidden."
        ),
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional execution context parameters.",
    )

    @field_validator("connection_id")
    @classmethod
    def forbid_raw_uris(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("connection_id must not be empty.")
        if "://" in clean or "@" in clean:
            raise ValueError(
                "Raw database connection URIs are forbidden. Use a registered connection_id."
            )
        return clean


class AgentRunSummaryResponse(BaseModel):
    """Summary of an initiated or executing agent run."""

    run_id: str
    tenant_id: str
    user_id: str
    connection_id: str
    current_state: str
    created_at: str
    updated_at: str


class HumanApprovalActionRequest(BaseModel):
    """Transition command for gated agent actions awaiting human decision."""

    action: Literal["approve", "reject", "cancel"]
    comment: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional human reviewer rationale.",
    )


class ErrorResponse(BaseModel):
    """Standardized API error envelope."""

    error_code: str
    message: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
