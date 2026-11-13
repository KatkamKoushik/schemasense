"""Typed Pydantic V2 execution state models for SchemaSense 2.0 Agent lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemasense.agent.lifecycle import AgentExecutionState, ApprovalStatus


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolInvocationRequest(BaseModel):
    """Declarative request to execute a registered agent tool."""

    model_config = ConfigDict(extra="ignore")

    tool_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(default_factory=lambda: str(uuid4()))
    is_high_risk: bool = False


class ToolInvocationResult(BaseModel):
    """Result of a tool execution with duration and error handling."""

    model_config = ConfigDict(extra="ignore")

    tool_name: str
    idempotency_key: str = ""
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class AuditRecordEntry(BaseModel):
    """Sanitized machine-readable audit trail entry for compliance."""

    model_config = ConfigDict(extra="ignore")

    timestamp: str = Field(default_factory=_utc_now_iso)
    state: str
    event: str
    details: dict[str, Any] = Field(default_factory=dict)


class AgentState(BaseModel):
    """Durable state container for the SchemaSense 12-state LangGraph lifecycle.

    Strict security invariant: This state container must NEVER hold raw database
    credentials, passwords, or connection strings. All database targets must be
    referenced exclusively by their server-managed `connection_id`.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "default"
    user_id: str = "system"
    user_roles: list[str] = Field(default_factory=lambda: ["user"])
    connection_id: str

    goal: str
    context: dict[str, Any] = Field(default_factory=dict)

    current_state: AgentExecutionState = AgentExecutionState.RECEIVE
    state_history: list[str] = Field(default_factory=list)

    plan: list[str] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    tool_requests: list[ToolInvocationRequest] = Field(default_factory=list)
    tool_results: list[ToolInvocationResult] = Field(default_factory=list)

    confidence_score: float = 1.0
    confidence_factors: dict[str, float] = Field(default_factory=dict)

    requires_approval: bool = False
    approval_gate_reason: str | None = None
    approval_status: ApprovalStatus = ApprovalStatus.NONE
    approval_requested_at: str | None = None
    approval_decided_at: str | None = None
    approval_decision_by: str | None = None
    approval_reason: str | None = None

    generated_sql: str | None = None
    target_tables: list[str] = Field(default_factory=list)
    final_response: dict[str, Any] | None = None

    audit_events: list[AuditRecordEntry] = Field(default_factory=list)
    error: str | None = None
    is_terminal: bool = False

    @field_validator("connection_id")
    @classmethod
    def validate_connection_id(cls, v: str) -> str:
        """Enforces that connection_id is an opaque reference and never a raw connection string."""
        if not v or not v.strip():
            raise ValueError("connection_id must not be empty.")
        clean = v.strip()
        lower = clean.lower()
        if (
            "://" in lower
            or "@" in lower
            or "password" in lower
            or lower.startswith("postgres")
            or lower.startswith("mysql")
            or lower.startswith("sqlite")
        ):
            raise ValueError(
                "connection_id must be a safe reference ID, not a raw connection URI or credential."
            )
        return clean

    def record_transition(self, new_state: AgentExecutionState) -> None:
        """Records state transition and appends to history."""
        self.current_state = new_state
        self.state_history.append(new_state.value)

    def record_audit(
        self, state: str, event: str, details: dict[str, Any] | None = None
    ) -> None:
        """Records a sanitized audit event."""
        clean_details = dict(details or {})
        # Sanitize any potential sensitive keys
        for key in list(clean_details.keys()):
            if any(
                secret_word in key.lower()
                for secret_word in ("password", "secret", "token", "key", "uri")
            ):
                clean_details[key] = "[REDACTED]"
        self.audit_events.append(
            AuditRecordEntry(
                timestamp=_utc_now_iso(),
                state=state,
                event=event,
                details=clean_details,
            )
        )

    def to_safe_dict(self) -> dict[str, Any]:
        """Returns serialization safe for external API/SSE delivery."""
        data = self.model_dump()
        return data
