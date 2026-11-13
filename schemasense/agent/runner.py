"""High-level execution runner and transition manager for SchemaSense 2.0 Agent lifecycle."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from schemasense.agent.checkpointer import get_checkpointer
from schemasense.agent.graph import create_agent_graph
from schemasense.agent.lifecycle import ApprovalAction, ApprovalStatus
from schemasense.agent.state import AgentState

logger = logging.getLogger("schemasense.agent.runner")

# Global singleton checkpointer & graph for in-process memory runs
_GLOBAL_CHECKPOINTER: BaseCheckpointSaver = get_checkpointer("memory")
_GLOBAL_GRAPH: CompiledStateGraph = create_agent_graph(_GLOBAL_CHECKPOINTER)


def reset_agent_runner() -> None:
    """Resets global in-memory checkpointer and agent graph (useful for test isolation)."""
    global _GLOBAL_CHECKPOINTER, _GLOBAL_GRAPH
    _GLOBAL_CHECKPOINTER = get_checkpointer("memory")
    _GLOBAL_GRAPH = create_agent_graph(_GLOBAL_CHECKPOINTER)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_agent_run(
    initial_state: AgentState,
    graph: CompiledStateGraph | None = None,
) -> AgentState:
    """Initiates an agent lifecycle execution run.

    Runs until completion or until paused before HUMAN_APPROVAL gate.
    """
    active_graph = graph or _GLOBAL_GRAPH
    config: RunnableConfig = {"configurable": {"thread_id": initial_state.run_id}}

    # Invoke graph with the initial state
    active_graph.invoke(initial_state, config=config)

    # Fetch snapshot from checkpoint
    snapshot = active_graph.get_state(config)
    values = snapshot.values
    if isinstance(values, AgentState):
        return values
    return AgentState.model_validate(values)


def resume_agent_run(
    run_id: str,
    action: ApprovalAction | str,
    actor: str = "reviewer",
    reason: str | None = None,
    graph: CompiledStateGraph | None = None,
) -> AgentState:
    """Resumes a paused agent execution run after human approval decision.

    Supported actions:
    - APPROVE: Proceed to tool execution.
    - REJECT: Terminate and record audit rejection.
    - EXPIRE: Terminate due to approval timeout.
    - CANCEL: Terminate due to caller cancellation.
    """
    active_graph = graph or _GLOBAL_GRAPH
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}

    # Normalize action
    action_str = action.value if isinstance(action, ApprovalAction) else str(action)
    action_enum = ApprovalAction(action_str)

    status_map = {
        ApprovalAction.APPROVE: ApprovalStatus.APPROVED,
        ApprovalAction.REJECT: ApprovalStatus.REJECTED,
        ApprovalAction.EXPIRE: ApprovalStatus.EXPIRED,
        ApprovalAction.CANCEL: ApprovalStatus.CANCELLED,
    }
    target_status = status_map[action_enum]

    # Update state at the interrupt checkpoint
    update_payload: dict[str, Any] = {
        "approval_status": target_status,
        "approval_decision_by": actor,
        "approval_decided_at": _utc_now_iso(),
        "approval_reason": reason,
    }
    active_graph.update_state(config, update_payload)

    # Resume graph execution
    active_graph.invoke(None, config=config)

    # Fetch snapshot after completion
    snapshot = active_graph.get_state(config)
    values = snapshot.values
    if isinstance(values, AgentState):
        return values
    return AgentState.model_validate(values)


def get_agent_run_state(
    run_id: str,
    graph: CompiledStateGraph | None = None,
) -> AgentState | None:
    """Retrieves current execution state snapshot for a given run_id."""
    active_graph = graph or _GLOBAL_GRAPH
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}
    snapshot = active_graph.get_state(config)
    if not snapshot or not snapshot.values:
        return None
    values = snapshot.values
    if isinstance(values, AgentState):
        return values
    return AgentState.model_validate(values)
