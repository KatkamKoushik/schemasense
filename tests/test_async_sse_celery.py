"""Unit and integration tests for SchemaSense 2.0 Async SSE Streaming and Dual-Mode Background Tasks.

Covers:
1. W3C SSE standard compliance and monotonic event sequencing.
2. SSE ring buffer retention and reconnection replay with Last-Event-ID.
3. Dual-mode task dispatcher enforcing strict operational boundaries (Mandatory Correction 12).
4. Celery at-least-once task configuration and bounded retries.
5. FastAPI agent lifecycle routes, verified identity derivation, and cross-tenant isolation.
6. Human approval decision transitions and event streaming replay.
7. Asynchronous schema profiling dispatch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

# Optional platform dependencies
pytest.importorskip("fastapi", reason="FastAPI is an optional platform dependency")
pytest.importorskip("langgraph", reason="LangGraph is an optional platform dependency")

from fastapi.testclient import TestClient

from schemasense.agent import (
    clear_connection_engines,
    get_agent_run_state,
    register_connection_engine,
    reset_agent_runner,
)
from schemasense.api.app import create_app
from schemasense.api.events import EventStore, SSEEvent, get_event_store
from schemasense.config import (
    PlatformConfig,
    clear_connection_references,
    register_connection_reference,
    set_platform_config,
)
from schemasense.tasks import (
    QueueUnavailableError,
    TaskDispatcher,
    clear_idempotency_cache,
    get_celery_app,
    is_celery_available,
)
from schemasense.tasks.tasks import (
    run_agent_lifecycle_core,
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


@pytest.fixture(autouse=True)
def cleanup_environment() -> Generator[None, None, None]:
    """Cleans up in-memory stores, engines, and references before and after each test."""
    clear_connection_engines()
    clear_connection_references()
    clear_idempotency_cache()
    get_event_store().clear()
    reset_agent_runner()

    yield

    clear_connection_engines()
    clear_connection_references()
    clear_idempotency_cache()
    get_event_store().clear()
    reset_agent_runner()


@pytest.fixture
def test_db_setup() -> Generator[dict[str, str], None, None]:
    """Registers an in-memory SQLite database and connection reference."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    metadata = MetaData()
    Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
        Column("email", String(100), nullable=False),
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

    conn_id = f"conn_{uuid.uuid4().hex[:8]}"
    register_connection_reference(
        connection_id=conn_id,
        database_uri="sqlite:///:memory:",
        name="Production Alpha",
        tenant_id="tenant-alpha",
    )
    register_connection_engine(conn_id, engine)

    yield {"connection_id": conn_id, "tenant_id": "tenant-alpha"}


@pytest.fixture
def simple_config() -> PlatformConfig:
    cfg = PlatformConfig(
        mode="simple",
        jwt_secret_key="test-secret-key-123",
        cors_allowed_origins=["http://localhost:8501"],
    )
    set_platform_config(cfg)
    return cfg


@pytest.fixture
def client(simple_config: PlatformConfig) -> TestClient:
    app = create_app(simple_config)
    return TestClient(app)


# ─────────────────────────────────────────────────────────────
# 1. W3C SSE STREAMING & MONOTONIC EVENT SEQUENCING
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sse_event_formatting_w3c() -> None:
    """Verifies that SSEEvent serializes into RFC-compliant W3C text/event-stream frames."""
    event = SSEEvent(
        event_id=1,
        run_id="run-test",
        event_type="agent_state",
        data={"state": "plan", "confidence": 0.85},
        timestamp="2026-11-13T20:00:00Z",
    )
    frame = event.to_sse_frame()
    assert frame.startswith("id: 1\n")
    assert "event: agent_state\n" in frame
    assert 'data: {"state": "plan", "confidence": 0.85}' in frame
    assert frame.endswith("\n\n")


@pytest.mark.unit
def test_sse_event_monotonic_sequencing() -> None:
    """Verifies that events for a run receive strictly monotonically increasing sequential IDs."""
    store = EventStore()
    run_id = "run-seq-test"

    e1 = store.record_event(run_id, "receive", {"step": 1})
    e2 = store.record_event(run_id, "understand", {"step": 2})
    e3 = store.record_event(run_id, "plan", {"step": 3})

    assert e1.event_id == 1
    assert e2.event_id == 2
    assert e3.event_id == 3

    # Distinct runs must have independent sequential sequences starting at 1
    other_e1 = store.record_event("run-other", "receive", {"step": 1})
    assert other_e1.event_id == 1


@pytest.mark.unit
def test_sse_reconnection_replay_with_last_event_id() -> None:
    """Verifies replay buffer correctly returns only events occurring after since_id."""
    store = EventStore()
    run_id = "run-replay-test"

    store.record_event(run_id, "ev1", {"num": 1})
    store.record_event(run_id, "ev2", {"num": 2})
    store.record_event(run_id, "ev3", {"num": 3})
    store.record_event(run_id, "ev4", {"num": 4})

    # Replay all events
    all_events = store.get_events(run_id, since_id=0)
    assert len(all_events) == 4
    assert [e.event_id for e in all_events] == [1, 2, 3, 4]

    # Replay after event 2 (simulating Last-Event-ID: 2)
    replayed = store.get_events(run_id, since_id=2)
    assert len(replayed) == 2
    assert [e.event_id for e in replayed] == [3, 4]

    # Replay after latest event (nothing missed)
    up_to_date = store.get_events(run_id, since_id=4)
    assert len(up_to_date) == 0


@pytest.mark.unit
def test_sse_ring_buffer_retention_limit() -> None:
    """Verifies ring buffer evicts oldest events while maintaining monotonic event_ids."""
    store = EventStore(max_buffer_per_run=3)
    run_id = "run-buffer-test"

    for i in range(1, 6):
        store.record_event(run_id, f"step_{i}", {"val": i})

    # Total recorded is 5, but buffer should only retain the latest 3
    buffered = store.get_events(run_id, since_id=0)
    assert len(buffered) == 3
    assert [e.event_id for e in buffered] == [3, 4, 5]


# ─────────────────────────────────────────────────────────────
# 2. DUAL-MODE TASK DISPATCHER & RELIABILITY CONTRACT
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_task_dispatcher_simple_mode_synchronous(test_db_setup: dict[str, str]) -> None:
    """In Simple Mode, tasks execute synchronously and in-process without Celery/Redis."""
    cfg = PlatformConfig(mode="simple")
    set_platform_config(cfg)

    run_id = "test-sync-run-001"
    conn_id = test_db_setup["connection_id"]
    tenant_id = test_db_setup["tenant_id"]

    res_id = TaskDispatcher.dispatch_agent_run(
        run_id=run_id,
        tenant_id=tenant_id,
        user_id="user-001",
        connection_id=conn_id,
        goal="Count total customers",
        context={"allowed_tables": ["customers"]},
    )

    assert res_id == run_id

    # Verify state was saved and executed
    state = get_agent_run_state(run_id)
    assert state is not None
    assert state.is_terminal is True
    assert len(state.tool_results) >= 1

    # Verify events were streamed into EventStore
    events = get_event_store().get_events(run_id)
    assert len(events) >= 3
    event_types = [e.event_type for e in events]
    assert "run_started" in event_types
    assert "state_transition" in event_types
    assert "run_completed" in event_types


@pytest.mark.unit
def test_task_dispatcher_advanced_mode_fails_fast_on_queue_outage() -> None:
    """Mandatory Correction 12: In Advanced Mode, failures to enqueue MUST raise QueueUnavailableError.

    Never silently downgrade to synchronous execution during a Celery/Redis outage.
    """
    cfg = PlatformConfig(mode="advanced")
    set_platform_config(cfg)

    # Simulate Celery broker outage by mocking execute_agent_run_task.delay raising Exception
    with patch("schemasense.tasks.dispatcher.execute_agent_run_task") as mock_task:
        mock_task.delay.side_effect = ConnectionError(
            "Redis broker is offline: connection refused"
        )

        with pytest.raises(QueueUnavailableError) as exc_info:
            TaskDispatcher.dispatch_agent_run(
                run_id="run-adv-fail",
                tenant_id="tenant-alpha",
                user_id="user-001",
                connection_id="conn-123",
                goal="Check database",
            )

        assert "Distributed task queue outage" in str(exc_info.value)

    # Profiling dispatch must also fail fast without silent downgrade
    with patch("schemasense.tasks.dispatcher.execute_profiling_task") as mock_task:
        mock_task.delay.side_effect = TimeoutError("Celery broker timeout")

        with pytest.raises(QueueUnavailableError) as exc_info:
            TaskDispatcher.dispatch_profiling(
                connection_id="conn-123",
                tenant_id="tenant-alpha",
                user_id="user-001",
            )

        assert "Distributed task queue outage" in str(exc_info.value)


@pytest.mark.unit
def test_task_dispatcher_advanced_mode_dispatches_when_available() -> None:
    """In Advanced Mode, successful Celery dispatch returns the distributed task UUID."""
    cfg = PlatformConfig(mode="advanced")
    set_platform_config(cfg)

    mock_async_result = MagicMock()
    mock_async_result.id = "celery-task-uuid-999"

    with patch("schemasense.tasks.dispatcher.execute_agent_run_task") as mock_task:
        mock_task.delay.return_value = mock_async_result

        task_id = TaskDispatcher.dispatch_agent_run(
            run_id="run-adv-success",
            tenant_id="tenant-alpha",
            user_id="user-001",
            connection_id="conn-123",
            goal="Analyze transactions",
        )

        assert task_id == "celery-task-uuid-999"
        mock_task.delay.assert_called_once()


@pytest.mark.unit
def test_celery_task_at_least_once_configuration() -> None:
    """Mandatory Correction 11: Celery must be configured with acks_late and crash requeue."""
    if not is_celery_available():
        pytest.skip("Celery is not installed in this environment")

    celery_app = get_celery_app()
    assert celery_app is not None
    conf = celery_app.conf

    # Strict durability requirements
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.task_time_limit == 300


@pytest.mark.unit
def test_idempotency_caching_behavior(test_db_setup: dict[str, str]) -> None:
    """Mandatory Correction 11: Duplicate requests with same idempotency_key return cached results."""
    conn_id = test_db_setup["connection_id"]
    tenant_id = test_db_setup["tenant_id"]

    idempotency_key = "idemp-key-unique-789"

    # First execution
    res1 = run_agent_lifecycle_core(
        run_id="run-idem-1",
        tenant_id=tenant_id,
        user_id="user-001",
        connection_id=conn_id,
        goal="Select count from customers",
        idempotency_key=idempotency_key,
    )

    # Second execution with same idempotency key
    res2 = run_agent_lifecycle_core(
        run_id="run-idem-2",
        tenant_id=tenant_id,
        user_id="user-001",
        connection_id=conn_id,
        goal="Different prompt with same key",
        idempotency_key=idempotency_key,
    )

    assert res1 == res2
    assert res2["run_id"] == "run-idem-1"  # Returns original run details


# ─────────────────────────────────────────────────────────────
# 3. FASTAPI AGENT ROUTES & IDENTITY ENFORCEMENT
# ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_api_create_agent_run_authenticated(
    client: TestClient, test_db_setup: dict[str, str]
) -> None:
    """Tests POST /api/v1/agent/runs with cryptographic JWT authentication and verified identity."""
    conn_id = test_db_setup["connection_id"]
    token = _generate_test_jwt(
        {"sub": "user_42", "tenant_id": "tenant-alpha", "roles": ["analyst"]}
    )

    payload = {
        "prompt": "Find all customers with invalid emails",
        "connection_id": conn_id,
        "parameters": {"allowed_tables": ["customers"]},
    }

    resp = client.post(
        "/api/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["tenant_id"] == "tenant-alpha"
    assert data["user_id"] == "user_42"
    assert data["connection_id"] == conn_id
    assert "event_stream_url" in data


@pytest.mark.unit
def test_api_create_agent_run_cross_tenant_forbidden(
    client: TestClient, test_db_setup: dict[str, str]
) -> None:
    """Verifies that requesting a connection belonging to another tenant is rejected with 403."""
    conn_id = test_db_setup["connection_id"]  # belongs to tenant-alpha
    # Token from tenant-beta
    token = _generate_test_jwt(
        {"sub": "user_evil", "tenant_id": "tenant-beta", "roles": ["analyst"]}
    )

    resp = client.post(
        "/api/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "Read customer data", "connection_id": conn_id},
    )

    assert resp.status_code == 403
    assert "not authorized" in resp.json()["detail"].lower()


@pytest.mark.unit
def test_api_get_agent_run_detail(
    client: TestClient, test_db_setup: dict[str, str]
) -> None:
    """Tests GET /api/v1/agent/runs/{run_id} retrieval and state history."""
    conn_id = test_db_setup["connection_id"]
    token = _generate_test_jwt(
        {"sub": "user_42", "tenant_id": "tenant-alpha", "roles": ["analyst"]}
    )

    # 1. Initiate run
    create_resp = client.post(
        "/api/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "Count rows in customers", "connection_id": conn_id},
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    # 2. Get run details
    get_resp = client.get(
        f"/api/v1/agent/runs/{run_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["run_id"] == run_id
    assert detail["is_terminal"] is True
    assert len(detail["state_history"]) >= 4

    # 3. Unauthorized cross-tenant retrieval
    other_tenant_token = _generate_test_jwt(
        {"sub": "other_user", "tenant_id": "tenant-gamma", "roles": ["analyst"]}
    )
    cross_resp = client.get(
        f"/api/v1/agent/runs/{run_id}",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )
    assert cross_resp.status_code == 403


@pytest.mark.unit
def test_api_human_approval_decision_workflow(
    client: TestClient, test_db_setup: dict[str, str]
) -> None:
    """Tests human approval submission, role authorization, and state resumption."""
    conn_id = test_db_setup["connection_id"]
    analyst_token = _generate_test_jwt(
        {"sub": "analyst_1", "tenant_id": "tenant-alpha", "roles": ["analyst"]}
    )
    viewer_token = _generate_test_jwt(
        {"sub": "viewer_1", "tenant_id": "tenant-alpha", "roles": ["viewer"]}
    )

    # 1. Create a run that triggers approval (Query execution requiring approval)
    create_resp = client.post(
        "/api/v1/agent/runs",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "prompt": "SELECT * FROM customers",
            "connection_id": conn_id,
        },
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    detail_resp = client.get(
        f"/api/v1/agent/runs/{run_id}",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["requires_approval"] is True
    assert detail_resp.json()["approval_status"] == "pending"
    assert detail_resp.json()["is_terminal"] is False
    assert len(detail_resp.json()["tool_results"]) == 0

    # 2. Viewer role attempts approval decision -> Forbidden (403)
    viewer_action_resp = client.post(
        f"/api/v1/agent/runs/{run_id}/approval",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"action": "approve", "comment": "Trying to bypass as viewer"},
    )
    assert viewer_action_resp.status_code == 403
    assert "analysts or admins" in viewer_action_resp.json()["detail"]

    # 3. Analyst rejects execution -> Successful transition to reject/terminal
    reject_resp = client.post(
        f"/api/v1/agent/runs/{run_id}/approval",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"action": "reject", "comment": "Query denied by analyst"},
    )
    assert reject_resp.status_code == 200
    updated = reject_resp.json()
    assert updated["approval_status"] == "rejected"
    assert updated["is_terminal"] is True


@pytest.mark.unit
def test_api_sse_event_streaming_with_replay(
    client: TestClient, test_db_setup: dict[str, str]
) -> None:
    """Tests GET /api/v1/agent/runs/{run_id}/events SSE format and Last-Event-ID replay."""
    conn_id = test_db_setup["connection_id"]
    token = _generate_test_jwt(
        {"sub": "user_42", "tenant_id": "tenant-alpha", "roles": ["analyst"]}
    )

    # 1. Create run and execute
    create_resp = client.post(
        "/api/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"prompt": "Count customers", "connection_id": conn_id},
    )
    run_id = create_resp.json()["run_id"]

    # 2. Replay all events via SSE endpoint
    sse_resp = client.get(
        f"/api/v1/agent/runs/{run_id}/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sse_resp.status_code == 200
    assert "text/event-stream" in sse_resp.headers["content-type"]
    body = sse_resp.text
    assert "id: 1\n" in body
    assert "event: run_started\n" in body
    assert "event: run_completed\n" in body

    # 3. Reconnect with Last-Event-ID: 2 (should replay events 3+)
    reconnect_resp = client.get(
        f"/api/v1/agent/runs/{run_id}/events",
        headers={
            "Authorization": f"Bearer {token}",
            "Last-Event-ID": "2",
        },
    )
    assert reconnect_resp.status_code == 200
    reconnect_body = reconnect_resp.text
    assert "id: 1\n" not in reconnect_body
    assert "id: 2\n" not in reconnect_body
    assert "id: 3\n" in reconnect_body


@pytest.mark.unit
def test_api_async_profiling_dual_mode(
    client: TestClient, test_db_setup: dict[str, str]
) -> None:
    """Tests POST /api/v1/agent/profiling in Simple Mode and error handling in Advanced Mode."""
    conn_id = test_db_setup["connection_id"]
    token = _generate_test_jwt(
        {"sub": "user_42", "tenant_id": "tenant-alpha", "roles": ["analyst"]}
    )

    # Simple Mode execution
    resp = client.post(
        "/api/v1/agent/profiling",
        headers={"Authorization": f"Bearer {token}"},
        json={"connection_id": conn_id, "table_names": ["customers"]},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["connection_id"] == conn_id
    assert data["status"] == "completed"

    # Advanced Mode failure scenario
    adv_cfg = PlatformConfig(
        mode="advanced",
        jwt_secret_key="test-secret-key-123",
    )
    set_platform_config(adv_cfg)

    with patch("schemasense.tasks.dispatcher.execute_profiling_task") as mock_task:
        mock_task.delay.side_effect = ConnectionError("Queue offline")

        adv_resp = client.post(
            "/api/v1/agent/profiling",
            headers={"Authorization": f"Bearer {token}"},
            json={"connection_id": conn_id, "table_names": ["customers"]},
        )
        assert adv_resp.status_code == 503
        assert "Distributed task queue outage" in adv_resp.json()["detail"]
