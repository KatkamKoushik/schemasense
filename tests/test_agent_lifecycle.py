"""Unit tests for SchemaSense 2.0 12-state LangGraph Agent Lifecycle and Typed Tools."""

from __future__ import annotations

import os
from typing import Generator

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

# Gracefully skip if optional platform dependency langgraph is not installed
pytest.importorskip("langgraph", reason="LangGraph is an optional platform dependency")

from schemasense.agent import (
    AgentExecutionState,
    AgentState,
    ApprovalAction,
    ApprovalStatus,
    ProfileColumnTool,
    ScanPIITool,
    ValidateSQLTool,
    clear_connection_engines,
    register_connection_engine,
    resume_agent_run,
    start_agent_run,
)
from schemasense.agent.tools import ExecutionContext
from schemasense.sql_guard import SQLGuard


@pytest.fixture(autouse=True)
def cleanup_engines() -> Generator[None, None, None]:
    """Ensures connection engine registry is cleared before and after each test."""
    clear_connection_engines()
    yield
    clear_connection_engines()


@pytest.fixture
def test_db_engine():
    """Creates a sample SQLite database engine with tables for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    metadata = MetaData()

    Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
        Column("email", String(100), nullable=False),
    )

    Table(
        "orders",
        metadata,
        Column("order_id", Integer, primary_key=True),
        Column("customer_id", Integer, nullable=False),
        Column("amount", Integer, nullable=False),
    )

    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            metadata.tables["customers"].insert(),
            [
                {"id": 1, "name": "Alice Smith", "email": "alice@example.com"},
                {"id": 2, "name": "Bob Jones", "email": "bob@example.com"},
            ],
        )
        conn.execute(
            metadata.tables["orders"].insert(),
            [
                {"order_id": 101, "customer_id": 1, "amount": 250},
                {"order_id": 102, "customer_id": 2, "amount": 450},
            ],
        )

    return engine


def test_12_state_linear_execution_read_only(test_db_engine):
    """Verifies complete linear traversal of lifecycle states for safe read-only operations."""
    conn_id = "conn_sqlite_test_01"
    register_connection_engine(conn_id, test_db_engine)

    initial_state = AgentState(
        goal="Inspect database schema and list available tables",
        connection_id=conn_id,
        user_roles=["analyst"],
    )

    result_state = start_agent_run(initial_state)

    assert result_state.is_terminal is True
    assert result_state.error is None
    assert result_state.current_state == AgentExecutionState.AUDIT_AND_LEARN

    # Verify key lifecycle states were traversed
    assert "receive" in result_state.state_history
    assert "understand" in result_state.state_history
    assert "plan" in result_state.state_history
    assert "select_tools" in result_state.state_history
    assert "check_permissions" in result_state.state_history
    assert "validate_preconditions" in result_state.state_history
    assert "score_confidence" in result_state.state_history
    assert "execute" in result_state.state_history
    assert "verify" in result_state.state_history
    assert "deliver" in result_state.state_history
    assert "audit_and_learn" in result_state.state_history

    # Verify tool output
    assert result_state.final_response is not None
    assert len(result_state.tool_results) >= 1

    schema_result = next(
        (r for r in result_state.tool_results if r.tool_name == "inspect_schema"), None
    )
    assert schema_result is not None
    assert schema_result.success is True
    assert "customers" in schema_result.output["tables"]
    assert "orders" in schema_result.output["tables"]


def test_pre_execution_human_approval_gate_and_approval(test_db_engine):
    """Verifies that high-risk queries pause BEFORE execution and proceed upon approval."""
    conn_id = "conn_sqlite_query_test"
    register_connection_engine(conn_id, test_db_engine)

    # A goal requesting SELECT query triggers high-risk ExecuteSafeQueryTool
    initial_state = AgentState(
        goal="Run SELECT * FROM customers to inspect records",
        connection_id=conn_id,
        user_roles=["analyst"],
        context={"sql": "SELECT id, name FROM customers;", "dialect": "sqlite"},
    )

    # First invocation should pause at HUMAN_APPROVAL
    paused_state = start_agent_run(initial_state)

    assert paused_state.requires_approval is True
    assert paused_state.approval_status == ApprovalStatus.PENDING
    assert paused_state.approval_gate_reason is not None
    assert paused_state.is_terminal is False

    # CRITICAL SECURITY INVARIANT: No tools have executed prior to approval!
    assert len(paused_state.tool_results) == 0

    # Human reviewer grants approval
    resumed_state = resume_agent_run(
        run_id=paused_state.run_id,
        action=ApprovalAction.APPROVE,
        actor="compliance_officer_sarah",
        reason="Approved for read-only analytical inspection",
    )

    assert resumed_state.is_terminal is True
    assert resumed_state.approval_status == ApprovalStatus.APPROVED
    assert resumed_state.approval_decision_by == "compliance_officer_sarah"
    assert "Approved for read-only" in (resumed_state.approval_reason or "")

    # Query was safely executed after approval
    query_result = next(
        (r for r in resumed_state.tool_results if r.tool_name == "execute_query"), None
    )
    assert query_result is not None
    assert query_result.success is True
    assert query_result.output["row_count"] == 2


def test_pre_execution_human_approval_rejection_transitions(test_db_engine):
    """Verifies reject, cancel, and expire transitions immediately terminate without tool execution."""
    conn_id = "conn_sqlite_reject_test"
    register_connection_engine(conn_id, test_db_engine)

    # 1. Test REJECT
    state_reject = AgentState(
        goal="SELECT * FROM customers",
        connection_id=conn_id,
        user_roles=["analyst"],
    )
    paused = start_agent_run(state_reject)
    assert paused.requires_approval is True

    rejected = resume_agent_run(
        run_id=paused.run_id,
        action=ApprovalAction.REJECT,
        actor="lead_dba",
        reason="Query accesses restricted customer PII",
    )
    assert rejected.is_terminal is True
    assert rejected.approval_status == ApprovalStatus.REJECTED
    assert "Query accesses restricted customer PII" in (rejected.error or "")
    assert len(rejected.tool_results) == 0

    # 2. Test CANCEL
    state_cancel = AgentState(
        goal="SELECT * FROM orders",
        connection_id=conn_id,
        user_roles=["analyst"],
    )
    paused_cancel = start_agent_run(state_cancel)
    cancelled = resume_agent_run(
        run_id=paused_cancel.run_id,
        action=ApprovalAction.CANCEL,
        actor="originating_user",
    )
    assert cancelled.is_terminal is True
    assert cancelled.approval_status == ApprovalStatus.CANCELLED
    assert len(cancelled.tool_results) == 0

    # 3. Test EXPIRE
    state_expire = AgentState(
        goal="SELECT * FROM customers",
        connection_id=conn_id,
        user_roles=["analyst"],
    )
    paused_expire = start_agent_run(state_expire)
    expired = resume_agent_run(
        run_id=paused_expire.run_id,
        action=ApprovalAction.EXPIRE,
        actor="system_watchdog",
    )
    assert expired.is_terminal is True
    assert expired.approval_status == ApprovalStatus.EXPIRED
    assert len(expired.tool_results) == 0


def test_permission_denial_fail_closed(test_db_engine):
    """Verifies that unauthorized users fail-closed at CHECK_PERMISSIONS."""
    conn_id = "conn_sqlite_perm_test"
    register_connection_engine(conn_id, test_db_engine)

    # Viewer attempting high-risk query execution
    initial_state = AgentState(
        goal="SELECT * FROM customers",
        connection_id=conn_id,
        user_roles=["viewer"],  # Viewers cannot run high-risk operations
    )

    result_state = start_agent_run(initial_state)

    assert result_state.is_terminal is True
    assert result_state.error is not None
    assert "Permission denied" in result_state.error
    assert len(result_state.tool_results) == 0
    # Should have routed straight to audit_and_learn
    assert "execute" not in result_state.state_history


def test_zero_secret_leakage_in_state():
    """Verifies that AgentState strictly rejects raw database URIs, passwords, or secrets."""
    # Attempt with raw PostgreSQL URI containing password
    with pytest.raises(ValueError, match="connection_id must be a safe reference ID"):
        AgentState(
            goal="Scan schema",
            connection_id="postgresql://admin:super_secret_password@db.prod:5432/finance",
        )

    # Attempt with MySQL connection string
    with pytest.raises(ValueError, match="connection_id must be a safe reference ID"):
        AgentState(
            goal="Scan schema",
            connection_id="mysql://user:pass@127.0.0.1:3306/db",
        )

    # Attempt with password parameter
    with pytest.raises(ValueError, match="connection_id must be a safe reference ID"):
        AgentState(
            goal="Scan schema",
            connection_id="conn_db_password_123",
        )

    # Safe opaque reference ID succeeds
    valid_state = AgentState(
        goal="Inspect schema",
        connection_id="conn_ref_enterprise_pg_01",
    )
    assert valid_state.connection_id == "conn_ref_enterprise_pg_01"

    # Verify serialization is safe
    safe_dict = valid_state.to_safe_dict()
    assert safe_dict["connection_id"] == "conn_ref_enterprise_pg_01"


def test_sqlguard_double_lock_gating():
    """Verifies SQLGuard AST validation and Stage C Double-Lock enforcement."""
    val_tool = ValidateSQLTool()
    ctx = ExecutionContext(
        tenant_id="default",
        user_id="alice",
        user_roles=["analyst"],
        connection_id="conn_dummy",
    )

    # Dangerous query (DROP TABLE) must be rejected
    res_drop = val_tool.execute(
        parameters={"sql_query": "DROP TABLE users;", "dialect": "postgres"},
        context=ctx,
    )
    assert res_drop.success is False
    assert "Only read-only SELECT" in (res_drop.error or "") or "DROP" in (
        res_drop.error or ""
    )

    # Double-lock enforcement when native core is unavailable
    old_enforce = SQLGuard.ENFORCE_DOUBLE_LOCK
    try:
        SQLGuard.ENFORCE_DOUBLE_LOCK = True
        os.environ["SCHEMASENSE_SQLGUARD_DOUBLE_LOCK"] = "1"

        # Validate SQL with double-lock
        res_double = val_tool.execute(
            parameters={"sql_query": "SELECT id FROM users;", "dialect": "postgres"},
            context=ctx,
        )
        # In an environment without native module or if native rejects, it must fail-closed
        from schemasense import is_native_core_available

        if not is_native_core_available():
            assert res_double.success is False
            assert "Strict Conjunction Failure" in (res_double.error or "")
    finally:
        SQLGuard.ENFORCE_DOUBLE_LOCK = old_enforce
        os.environ.pop("SCHEMASENSE_SQLGUARD_DOUBLE_LOCK", None)


def test_scan_pii_tool():
    """Verifies ScanPIITool correctly identifies sensitive entities."""
    pii_tool = ScanPIITool()
    ctx = ExecutionContext(
        tenant_id="default",
        user_id="alice",
        user_roles=["analyst"],
        connection_id="conn_dummy",
    )

    # Sample emails
    res_email = pii_tool.execute(
        parameters={"samples": ["alice@gmail.com", "bob@corp.org", "carol@domain.io"]},
        context=ctx,
    )
    assert res_email.success is True
    assert res_email.output["pii_detected"] == "EMAIL"
    assert res_email.output["is_sensitive"] is True

    # Non-PII samples
    res_plain = pii_tool.execute(
        parameters={"samples": ["product_123", "item_456", "sku_789"]},
        context=ctx,
    )
    assert res_plain.success is True
    assert res_plain.output["pii_detected"] is None
    assert res_plain.output["is_sensitive"] is False


def test_profile_column_tool(test_db_engine):
    """Verifies ProfileColumnTool extracts column statistics and distribution."""
    conn_id = "conn_sqlite_profile"
    register_connection_engine(conn_id, test_db_engine)

    prof_tool = ProfileColumnTool()
    ctx = ExecutionContext(
        tenant_id="default",
        user_id="alice",
        user_roles=["analyst"],
        connection_id=conn_id,
    )

    res = prof_tool.execute(
        parameters={
            "table_name": "customers",
            "column_name": "email",
            "max_sample_rows": 100,
        },
        context=ctx,
    )
    assert res.success is True
    assert res.output["table_name"] == "customers"
    assert res.output["column_name"] == "email"
    assert res.output["sample_size"] == 2
    assert res.output["null_count"] == 0
    assert res.output["distinct_count"] == 2
    assert res.output["pii_detected"] == "EMAIL"


def test_precondition_unregistered_connection_failure():
    """Verifies that execution with an unregistered connection_id fails closed."""
    initial_state = AgentState(
        goal="Inspect schema",
        connection_id="conn_does_not_exist_999",
        user_roles=["analyst"],
    )

    result_state = start_agent_run(initial_state)

    assert result_state.is_terminal is True
    assert result_state.error is not None
    assert "No active engine registered" in result_state.error
    assert len(result_state.tool_results) == 0
