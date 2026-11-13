"""001 Initial Platform Schema.

Revision ID: 001_initial_platform_schema
Revises: None
Create Date: 2026-11-13 19:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "001_initial_platform_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Tenants
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # 2. Users
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # 3. API Keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("hashed_secret", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])

    # 4. Connection References (Zero Plaintext Secrets)
    op.create_table(
        "connection_references",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("dialect", sa.String(length=32), nullable=False),
        sa.Column("encrypted_uri", sa.Text(), nullable=False),
        sa.Column("vault_pointer", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_connection_references_tenant_id", "connection_references", ["tenant_id"]
    )

    # 5. Agent Run Records
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "connection_id",
            sa.String(length=64),
            sa.ForeignKey("connection_references.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="pending"
        ),
        sa.Column(
            "current_state",
            sa.String(length=32),
            nullable=False,
            server_default="receive",
        ),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    # 6. Audit Event Records (Privacy-Safe Sanitized Details)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("agent_runs.run_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("sanitized_details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    # 7. Benchmark Evaluations
    op.create_table(
        "benchmark_evaluations",
        sa.Column("benchmark_run_id", sa.String(length=64), primary_key=True),
        sa.Column("agent_model", sa.String(length=64), nullable=False),
        sa.Column("suite_domain", sa.String(length=64), nullable=False),
        sa.Column("tasks_evaluated", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("tool_hallucination_rate", sa.Float(), nullable=False),
        sa.Column("avg_tokens_per_task", sa.Integer(), nullable=False),
        sa.Column("cost_per_solved_task", sa.Float(), nullable=False),
        sa.Column("regression_verdict", sa.String(length=32), nullable=False),
        sa.Column("evaluation_lead", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_benchmark_evaluations_agent_model", "benchmark_evaluations", ["agent_model"]
    )
    op.create_index(
        "ix_benchmark_evaluations_suite_domain",
        "benchmark_evaluations",
        ["suite_domain"],
    )


def downgrade() -> None:
    op.drop_table("benchmark_evaluations")
    op.drop_table("audit_events")
    op.drop_table("agent_runs")
    op.drop_table("connection_references")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("tenants")
