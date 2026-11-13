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
    event_stream_url: str | None = None


class HumanApprovalActionRequest(BaseModel):
    """Transition command for gated agent actions awaiting human decision."""

    action: Literal["approve", "reject", "cancel", "expire"]
    comment: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional human reviewer rationale.",
    )


class AgentRunDetailResponse(BaseModel):
    """Detailed snapshot of an agent run including state transitions and deliverables."""

    run_id: str
    tenant_id: str
    user_id: str
    connection_id: str
    goal: str
    current_state: str
    state_history: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    approval_status: str = "none"
    approval_gate_reason: str | None = None
    approval_decision_by: str | None = None
    confidence_score: float = 1.0
    generated_sql: str | None = None
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    final_response: dict[str, Any] | None = None
    error: str | None = None
    is_terminal: bool = False
    event_stream_url: str = ""
    created_at: str
    updated_at: str


class AsyncProfilingRequest(BaseModel):
    """Request to initiate asynchronous schema profiling and quality analysis."""

    connection_id: str
    table_names: list[str] | None = None
    idempotency_key: str | None = None

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


class ProfilingTaskResponse(BaseModel):
    """Response returned upon queueing or executing an async profiling task."""

    task_id: str
    connection_id: str
    tenant_id: str
    status: Literal["queued", "completed", "failed"]
    table_count: int = 0
    message: str = "Profiling job accepted"


class ErrorResponse(BaseModel):
    """Standardized API error envelope."""

    error_code: str
    message: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
