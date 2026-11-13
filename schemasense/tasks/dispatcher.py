"""Dual-mode task dispatcher enforcing strict operational boundaries.

Strict Reliability Invariant (Mandatory Correction 12):
The synchronous fallback executor is used ONLY in explicitly configured Simple Mode.
Advanced Mode MUST use the distributed Celery queue and fails fast with
QueueUnavailableError during an outage, never silently downgrading production workloads.
"""

from __future__ import annotations

import logging
from typing import Any

from schemasense.config import get_platform_config
from schemasense.tasks.celery_app import is_celery_available
from schemasense.tasks.tasks import (
    execute_agent_run_task,
    execute_profiling_task,
    run_agent_lifecycle_core,
    run_profiling_core,
)

logger = logging.getLogger("schemasense.tasks.dispatcher")


class QueueUnavailableError(RuntimeError):
    """Raised when Advanced Mode background queue is offline or unreachable."""


class TaskDispatcher:
    """Dispatches background tasks based on the active deployment mode."""

    @staticmethod
    def dispatch_agent_run(
        run_id: str,
        tenant_id: str,
        user_id: str,
        connection_id: str,
        goal: str,
        user_roles: list[str] | None = None,
        context: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Dispatches an agent lifecycle execution run.

        Returns:
            str: Task or run identifier.
        """
        cfg = get_platform_config()

        # 1. Simple Mode: Synchronous In-Process Execution (Permitted only in Simple Mode)
        if cfg.is_simple_mode:
            logger.info(
                "Executing agent run '%s' synchronously in Simple Mode.", run_id
            )
            run_agent_lifecycle_core(
                run_id=run_id,
                tenant_id=tenant_id,
                user_id=user_id,
                connection_id=connection_id,
                goal=goal,
                user_roles=user_roles,
                context=context,
                idempotency_key=idempotency_key,
            )
            return run_id

        # 2. Advanced Mode: Distributed Celery Execution
        if not is_celery_available() or execute_agent_run_task is None:
            raise QueueUnavailableError(
                "Celery task queue is not available in Advanced Mode. "
                "Ensure celery and redis dependencies are installed."
            )

        try:
            async_result = execute_agent_run_task.delay(
                run_id=run_id,
                tenant_id=tenant_id,
                user_id=user_id,
                connection_id=connection_id,
                goal=goal,
                user_roles=user_roles,
                context=context,
                idempotency_key=idempotency_key,
            )
            return str(async_result.id)
        except Exception as e:
            logger.exception("Failed to dispatch task to Celery broker: %s", e)
            # NEVER silently downgrade in Advanced Mode
            raise QueueUnavailableError(
                f"Distributed task queue outage: Failed to enqueue agent run: {e}"
            ) from e

    @staticmethod
    def dispatch_profiling(
        connection_id: str,
        tenant_id: str,
        user_id: str,
        table_names: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Dispatches an asynchronous schema profiling task."""
        cfg = get_platform_config()

        if cfg.is_simple_mode:
            logger.info(
                "Executing schema profiling for '%s' synchronously in Simple Mode.",
                connection_id,
            )
            run_profiling_core(
                connection_id=connection_id,
                tenant_id=tenant_id,
                user_id=user_id,
                table_names=table_names,
                idempotency_key=idempotency_key,
            )
            return f"sync_{connection_id}"

        if not is_celery_available() or execute_profiling_task is None:
            raise QueueUnavailableError(
                "Celery task queue is not available in Advanced Mode."
            )

        try:
            async_result = execute_profiling_task.delay(
                connection_id=connection_id,
                tenant_id=tenant_id,
                user_id=user_id,
                table_names=table_names,
                idempotency_key=idempotency_key,
            )
            return str(async_result.id)
        except Exception as e:
            logger.exception("Failed to dispatch profiling task to Celery: %s", e)
            raise QueueUnavailableError(
                f"Distributed task queue outage: Failed to enqueue profiling task: {e}"
            ) from e
