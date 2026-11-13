"""Celery background tasks for durable agent execution and asynchronous schema profiling."""

from __future__ import annotations

import logging
import threading
from typing import Any

from schemasense.agent import (
    AgentState,
    ApprovalStatus,
    InspectSchemaTool,
    start_agent_run,
)
from schemasense.agent.tools import ExecutionContext
from schemasense.api.events import get_event_store
from schemasense.tasks.celery_app import get_celery_app

logger = logging.getLogger("schemasense.tasks.tasks")

# In-memory idempotency cache for deduplication
_IDEMPOTENCY_CACHE: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_LOCK = threading.RLock()


def is_idempotent(key: str) -> bool:
    """Checks if an execution with the given idempotency key has already completed."""
    with _IDEMPOTENCY_LOCK:
        return key in _IDEMPOTENCY_CACHE


def record_idempotency_result(key: str, result: dict[str, Any]) -> None:
    """Stores the execution result for an idempotency key."""
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_CACHE[key] = result


def clear_idempotency_cache() -> None:
    """Clears the idempotency cache (used for test teardown)."""
    with _IDEMPOTENCY_LOCK:
        _IDEMPOTENCY_CACHE.clear()


# ─────────────────────────────────────────────────────────────
# CORE TASK LOGIC (INDEPENDENT OF CELERY RUNTIME)
# ─────────────────────────────────────────────────────────────
def run_agent_lifecycle_core(
    run_id: str,
    tenant_id: str,
    user_id: str,
    connection_id: str,
    goal: str,
    user_roles: list[str] | None = None,
    context: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Core execution engine for agent lifecycle runs with event sequencing."""
    event_store = get_event_store()

    # 1. Idempotency Check
    if idempotency_key and is_idempotent(idempotency_key):
        logger.info(
            "Idempotent hit for key '%s'; returning cached result.", idempotency_key
        )
        cached = _IDEMPOTENCY_CACHE[idempotency_key]
        event_store.record_event(
            run_id=run_id,
            event_type="idempotent_replay",
            data={"idempotency_key": idempotency_key, "run_id": run_id},
        )
        return cached

    # 2. Emit Run Started Event
    event_store.record_event(
        run_id=run_id,
        event_type="run_started",
        data={
            "run_id": run_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "connection_id": connection_id,
            "goal": goal,
        },
    )

    # 3. Instantiate State & Run 12-State Graph
    state = AgentState(
        run_id=run_id,
        tenant_id=tenant_id,
        user_id=user_id,
        user_roles=user_roles or ["user"],
        connection_id=connection_id,
        goal=goal,
        context=context or {},
    )

    final_state = start_agent_run(state)

    # 4. Record State Transitions in Sequenced Event Stream
    for st_name in final_state.state_history:
        event_store.record_event(
            run_id=run_id,
            event_type="state_transition",
            data={"state": st_name, "run_id": run_id},
        )

    # 5. Handle Approval Interruption Gate
    if (
        final_state.requires_approval
        and final_state.approval_status == ApprovalStatus.PENDING
    ):
        event_store.record_event(
            run_id=run_id,
            event_type="approval_required",
            data={
                "run_id": run_id,
                "gate_reason": final_state.approval_gate_reason,
                "confidence_score": final_state.confidence_score,
                "generated_sql": final_state.generated_sql,
            },
        )
        # Note: Do not close stream, waiting for human decision
        return final_state.to_safe_dict()

    # 6. Terminal Closure
    if final_state.error:
        event_store.record_event(
            run_id=run_id,
            event_type="run_failed",
            data={"error": final_state.error, "run_id": run_id},
        )
    else:
        event_store.record_event(
            run_id=run_id,
            event_type="run_completed",
            data={
                "run_id": run_id,
                "confidence_score": final_state.confidence_score,
                "has_deliverable": final_state.final_response is not None,
            },
        )

    result_dict = final_state.to_safe_dict()
    if idempotency_key:
        record_idempotency_result(idempotency_key, result_dict)

    event_store.close_stream(run_id)
    return result_dict


def run_profiling_core(
    connection_id: str,
    tenant_id: str,
    user_id: str,
    table_names: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Core execution engine for asynchronous schema profiling."""
    if idempotency_key and is_idempotent(idempotency_key):
        return _IDEMPOTENCY_CACHE[idempotency_key]

    tool = InspectSchemaTool()
    ctx = ExecutionContext(
        tenant_id=tenant_id,
        user_id=user_id,
        user_roles=["analyst"],
        connection_id=connection_id,
    )
    result = tool.execute(
        parameters={"table_names": table_names},
        context=ctx,
    )

    summary = {
        "connection_id": connection_id,
        "tenant_id": tenant_id,
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }

    if idempotency_key and result.success:
        record_idempotency_result(idempotency_key, summary)

    return summary


# ─────────────────────────────────────────────────────────────
# CELERY TASK WRAPPERS (Decorated when Celery is available)
# ─────────────────────────────────────────────────────────────
celery_app = get_celery_app()

if celery_app is not None:

    @celery_app.task(
        bind=True,
        max_retries=3,
        name="schemasense.tasks.execute_agent_run",
    )
    def execute_agent_run_task(
        self: Any,
        run_id: str,
        tenant_id: str,
        user_id: str,
        connection_id: str,
        goal: str,
        user_roles: list[str] | None = None,
        context: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Celery worker task with bounded retries and exponential backoff."""
        try:
            return run_agent_lifecycle_core(
                run_id=run_id,
                tenant_id=tenant_id,
                user_id=user_id,
                connection_id=connection_id,
                goal=goal,
                user_roles=user_roles,
                context=context,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error executing agent run task %s: %s", run_id, exc)
            if self.request.retries < self.max_retries:
                countdown = 2**self.request.retries
                raise self.retry(exc=exc, countdown=countdown) from exc
            raise

    @celery_app.task(
        bind=True,
        max_retries=3,
        name="schemasense.tasks.execute_profiling",
    )
    def execute_profiling_task(
        self: Any,
        connection_id: str,
        tenant_id: str,
        user_id: str,
        table_names: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Celery worker task for async schema profiling."""
        try:
            return run_profiling_core(
                connection_id=connection_id,
                tenant_id=tenant_id,
                user_id=user_id,
                table_names=table_names,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Error executing profiling task for %s: %s", connection_id, exc
            )
            if self.request.retries < self.max_retries:
                countdown = 2**self.request.retries
                raise self.retry(exc=exc, countdown=countdown) from exc
            raise
else:
    execute_agent_run_task = None  # type: ignore[assignment]
    execute_profiling_task = None  # type: ignore[assignment]
