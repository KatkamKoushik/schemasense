"""Durable and in-memory checkpointer provider for SchemaSense 2.0 Agent lifecycle."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger("schemasense.agent.checkpointer")


def get_checkpointer(
    checkpointer_type: str = "memory",
    connection_uri: str | None = None,
) -> Any:
    """Returns a LangGraph-compatible checkpointer instance.

    Defaults to MemorySaver for ephemeral or unit test executions.
    Supports AsyncPostgresSaver or SqliteSaver when running in Advanced Mode.
    """
    mode = (checkpointer_type or "memory").lower().strip()

    if mode == "memory":
        return MemorySaver()

    if mode == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import (  # type: ignore[import-not-found]
                SqliteSaver,
            )

            db_path = connection_uri or ":memory:"
            return SqliteSaver.from_conn_string(db_path)
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "SqliteSaver unavailable (%s); falling back to MemorySaver.", exc
            )
            return MemorySaver()

    if mode in ("postgres", "postgresql"):
        try:
            from langgraph_checkpoint_postgres.aio import (  # type: ignore[import-not-found]
                AsyncPostgresSaver,
            )

            if connection_uri:
                return AsyncPostgresSaver.from_conn_string(connection_uri)
            return MemorySaver()
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "AsyncPostgresSaver unavailable (%s); falling back to MemorySaver.", exc
            )
            return MemorySaver()

    logger.warning(
        "Unknown checkpointer_type '%s'; defaulting to MemorySaver.", checkpointer_type
    )
    return MemorySaver()
