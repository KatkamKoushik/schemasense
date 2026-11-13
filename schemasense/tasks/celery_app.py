"""Celery Application Factory and Configuration for SchemaSense 2.0.

Configures at-least-once task delivery, broker crash recovery, task leasing,
and bounded execution timeouts for Advanced Mode background workloads.
"""

from __future__ import annotations

import logging
from typing import Any

from schemasense.config import get_platform_config

logger = logging.getLogger("schemasense.tasks")


def is_celery_available() -> bool:
    """Returns True if Celery and Redis dependencies are installed in the runtime."""
    try:
        import celery  # noqa: F401
        import redis  # noqa: F401

        return True
    except ImportError:
        return False


_CELERY_APP: Any = None


def get_celery_app() -> Any:
    """Initializes and returns the singleton Celery application instance."""
    global _CELERY_APP
    if _CELERY_APP is not None:
        return _CELERY_APP

    if not is_celery_available():
        logger.debug("Celery is not installed in current environment.")
        return None

    from celery import Celery

    cfg = get_platform_config()
    broker_url = cfg.celery_broker_url or "redis://localhost:6379/0"
    backend_url = cfg.celery_result_backend or broker_url

    app = Celery("schemasense", broker=broker_url, backend=backend_url)

    # Mandatory Correction 11: At-least-once execution, durable leasing, bounded timeouts
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_time_limit=300,  # 5 minutes hard limit
        task_soft_time_limit=270,  # 4.5 minutes soft limit
        result_expires=3600,  # 1 hour result TTL
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
    )

    _CELERY_APP = app
    return _CELERY_APP
