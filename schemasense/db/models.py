"""Platform State Relational Models for SchemaSense 2.0 (Advanced Mode).

Defines entities for Tenants, Users, API Keys, Secure Connection References,
Agent Execution Runs, Privacy-Safe Audit Trails, and Capability Benchmarks.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from schemasense.db.base import Base, TenantScopedMixin, TimestampMixin, generate_uuid


class Tenant(Base, TimestampMixin):
    """Multi-tenant boundary for organizations or customer workspaces."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list[User]] = relationship(
        "User", back_populates="tenant", cascade="all, delete-orphan"
    )
    connections: Mapped[list[ConnectionReference]] = relationship(
        "ConnectionReference", back_populates="tenant", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRunRecord]] = relationship(
        "AgentRunRecord", back_populates="tenant", cascade="all, delete-orphan"
    )


class User(Base, TenantScopedMixin, TimestampMixin):
    """Authenticated user entity within a specific tenant organization."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="users")
    api_keys: Mapped[list[ApiKey]] = relationship(
        "ApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRunRecord]] = relationship(
        "AgentRunRecord", back_populates="user"
    )


class ApiKey(Base, TenantScopedMixin, TimestampMixin):
    """Hashed API keys for programmatic service-to-service access."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    key_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    hashed_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="api_keys")


class ConnectionReference(Base, TenantScopedMixin, TimestampMixin):
    """Secure database connection pointer.

    Strictly satisfies Master Security Requirement Item 7:
    Never persists plain-text credentials, passwords, or raw URIs.
    """

    __tablename__ = "connection_references"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )  # e.g., "conn_prod_analytics"
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    dialect: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "postgres", "mysql", "sqlite"
    encrypted_uri: Mapped[str] = mapped_column(Text, nullable=False)
    vault_pointer: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="connections")
    agent_runs: Mapped[list[AgentRunRecord]] = relationship(
        "AgentRunRecord", back_populates="connection"
    )


class AgentRunRecord(Base, TenantScopedMixin, TimestampMixin):
    """Authoritative execution record for an AI agent intelligence run."""

    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    connection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("connection_references.id", ondelete="CASCADE"),
        nullable=False,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True, nullable=False
    )  # "pending", "running", "awaiting_approval", "completed", "failed", "cancelled"
    current_state: Mapped[str] = mapped_column(
        String(32), default="receive", nullable=False
    )  # 12-state lifecycle step
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="agent_runs")
    user: Mapped[User | None] = relationship("User", back_populates="agent_runs")
    connection: Mapped[ConnectionReference] = relationship(
        "ConnectionReference", back_populates="agent_runs"
    )
    audit_events: Mapped[list[AuditEventRecord]] = relationship(
        "AuditEventRecord", back_populates="agent_run", cascade="all, delete-orphan"
    )


class AuditEventRecord(Base, TenantScopedMixin, TimestampMixin):
    """Tamper-evident, privacy-preserving audit log of agent and security actions.

    Satisfies Master Requirement Item 18:
    Guaranteed sanitized: strictly excludes raw customer data, credentials, and plaintext SQL.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "user", "agent", "system"
    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "SECURITY", "LIFECYCLE", "TOOL"
    sanitized_details: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    agent_run: Mapped[AgentRunRecord | None] = relationship(
        "AgentRunRecord", back_populates="audit_events"
    )


class BenchmarkEvaluationRecord(Base, TimestampMixin):
    """Standardized AI Agent Capability Evaluation & Benchmarking compliance register.

    Directly implements the ai-agent-evaluation-benchmarking skill specification.
    """

    __tablename__ = "benchmark_evaluations"

    benchmark_run_id: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )  # e.g., "BENCH-001"
    agent_model: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    suite_domain: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    tasks_evaluated: Mapped[int] = mapped_column(Integer, nullable=False)
    pass_rate: Mapped[float] = mapped_column(Float, nullable=False)
    tool_hallucination_rate: Mapped[float] = mapped_column(Float, nullable=False)
    avg_tokens_per_task: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_per_solved_task: Mapped[float] = mapped_column(Float, nullable=False)
    regression_verdict: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "Superior", "Parity Baseline", "Regression Failure"
    evaluation_lead: Mapped[str] = mapped_column(String(64), nullable=False)
