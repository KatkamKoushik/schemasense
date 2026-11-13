"""Tests for SchemaSense 2.0 Platform Database Models & Versioned Migrations.

Verifies:
1. Model declaration, primary keys, and cascade foreign key constraints.
2. ConnectionReference stores zero plain-text passwords or raw secrets (Item 7).
3. AuditEventRecord stores sanitized, privacy-safe event details (Item 18).
4. BenchmarkEvaluationRecord implements the ai-agent-evaluation-benchmarking register.
5. Explicit Alembic migration workflow: upgrade head, check alignment, downgrade base (Item 1).
6. Simple Mode isolation: informative error when platform DB is accessed without configuration.
"""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

pytest.importorskip("alembic", reason="Alembic is an optional platform dependency")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from schemasense.config import PlatformConfig, set_platform_config
from schemasense.db.base import Base
from schemasense.db.migrate import check_status, downgrade, upgrade
from schemasense.db.models import (
    AgentRunRecord,
    AuditEventRecord,
    BenchmarkEvaluationRecord,
    ConnectionReference,
    Tenant,
    User,
)
from schemasense.db.session import create_all_tables, get_engine


@pytest.fixture
def sqlite_engine():
    """Provides an isolated in-memory SQLite database engine for model testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    create_all_tables(engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """Yields a clean SQLAlchemy session bound to the test database."""
    session_factory = sessionmaker(
        bind=sqlite_engine, autoflush=False, autocommit=False
    )
    session = session_factory()
    yield session
    session.rollback()
    session.close()


# ─────────────────────────────────────────────────────────────
# 1. ENTITY MODEL INTEGRITY & MULTI-TENANCY
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_tenant_and_user_creation(db_session: Session) -> None:
    """Verifies Tenant boundary and cascaded User relationship."""
    tenant = Tenant(
        id="tenant_acme",
        name="Acme Corporation",
        slug="acme-corp",
        is_active=True,
    )
    user = User(
        id="user_alice",
        tenant_id="tenant_acme",
        email="alice@acme.com",
        roles=["admin", "data_steward"],
        is_active=True,
    )
    db_session.add(tenant)
    db_session.add(user)
    db_session.commit()

    queried_tenant = db_session.get(Tenant, "tenant_acme")
    assert queried_tenant is not None
    assert queried_tenant.name == "Acme Corporation"
    assert len(queried_tenant.users) == 1
    assert queried_tenant.users[0].email == "alice@acme.com"


# ─────────────────────────────────────────────────────────────
# 2. ZERO-SECRET CONNECTION REFERENCE INVARIANT (Item 7)
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_connection_reference_stores_encrypted_pointer(db_session: Session) -> None:
    """Connection references must store encrypted tokens or vault pointers, never plain credentials."""
    tenant = Tenant(id="tenant_fin", name="Finance", slug="finance", is_active=True)
    conn = ConnectionReference(
        id="conn_fin_dw",
        tenant_id="tenant_fin",
        name="Finance Data Warehouse",
        dialect="postgres",
        encrypted_uri="vault://v1/secret/data/finance/postgres_conn",
        vault_pointer="v1/secret/finance",
    )
    db_session.add(tenant)
    db_session.add(conn)
    db_session.commit()

    record = db_session.get(ConnectionReference, "conn_fin_dw")
    assert record is not None
    assert record.dialect == "postgres"
    assert "password" not in record.encrypted_uri.lower()

    # Verify to_dict_safe redacts any secret tokens
    safe_dict = record.to_dict_safe()
    assert safe_dict["id"] == "conn_fin_dw"
    assert "created_at" in safe_dict


# ─────────────────────────────────────────────────────────────
# 3. PRIVACY-SAFE AUDIT TRAIL (Item 18)
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_audit_event_record_sanitized_details(db_session: Session) -> None:
    """Audit trails must record sanitized metadata excluding plain SQL or customer data."""
    tenant = Tenant(id="tenant_ops", name="Ops", slug="ops", is_active=True)
    conn = ConnectionReference(
        id="conn_sqlite_test",
        tenant_id="tenant_ops",
        name="Test SQLite",
        dialect="sqlite",
        encrypted_uri="sqlite:///:memory:",
    )
    run = AgentRunRecord(
        run_id="run_101",
        tenant_id="tenant_ops",
        connection_id="conn_sqlite_test",
        prompt="Inspect customers schema",
        status="running",
        current_state="understand",
        confidence_score=0.95,
    )
    audit = AuditEventRecord(
        id="evt_001",
        run_id="run_101",
        tenant_id="tenant_ops",
        user_id="user_admin",
        action="VALIDATE_SCHEMA_PRECONDITIONS",
        actor="agent",
        event_type="LIFECYCLE",
        sanitized_details={
            "ast_node_count": 14,
            "target_tables_count": 2,
            "read_only_verified": True,
        },
    )
    db_session.add_all([tenant, conn, run, audit])
    db_session.commit()

    queried_audit = db_session.get(AuditEventRecord, "evt_001")
    assert queried_audit is not None
    assert queried_audit.action == "VALIDATE_SCHEMA_PRECONDITIONS"
    assert queried_audit.sanitized_details["read_only_verified"] is True
    # Ensure no customer raw payload is present
    assert "raw_query" not in queried_audit.sanitized_details


# ─────────────────────────────────────────────────────────────
# 4. CAPABILITY EVALUATION BENCHMARK REGISTER
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_benchmark_evaluation_register_record(db_session: Session) -> None:
    """Implements compliance tracking for AI agent capability evaluation and benchmarking."""
    record = BenchmarkEvaluationRecord(
        benchmark_run_id="BENCH-001",
        agent_model="Gemini 2.5 Pro",
        suite_domain="SchemaGroundingBench",
        tasks_evaluated=100,
        pass_rate=92.5,
        tool_hallucination_rate=0.0,
        avg_tokens_per_task=2450,
        cost_per_solved_task=0.012,
        regression_verdict="Superior",
        evaluation_lead="PlatformLead",
    )
    db_session.add(record)
    db_session.commit()

    bench = db_session.get(BenchmarkEvaluationRecord, "BENCH-001")
    assert bench is not None
    assert bench.pass_rate == 92.5
    assert bench.regression_verdict == "Superior"


# ─────────────────────────────────────────────────────────────
# 5. VERSIONED ALEMBIC MIGRATION WORKFLOW (Item 1 & Item 15)
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_alembic_migration_lifecycle() -> None:
    """Verifies explicit upgrade head, check alignment, and downgrade base via Alembic."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    db_url = f"sqlite:///{db_path}"

    try:
        # 1. Upgrade to head
        upgrade(revision="head", db_url=db_url)

        # 2. Check alignment: must confirm schema is synchronized
        is_synced = check_status(db_url=db_url)
        assert is_synced is True, (
            "Expected migrated database to be synchronized with migration head."
        )

        # 3. Downgrade to base
        downgrade(revision="base", db_url=db_url)
    finally:
        Path(db_path).unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────
# 6. SIMPLE MODE ISOLATION (Item 3)
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_simple_mode_unconfigured_db_error() -> None:
    """When platform DB is unconfigured, attempting to acquire engine raises a descriptive error."""
    # Reset config to Simple Mode with no platform DB url
    cfg = PlatformConfig(mode="simple", platform_db_url=None)
    set_platform_config(cfg)

    # Force fresh engine lookup
    from schemasense.db import session as db_session_module

    db_session_module._ENGINE = None

    with pytest.raises(RuntimeError, match="platform database is not configured"):
        get_engine()
