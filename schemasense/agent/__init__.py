"""SchemaSense 2.0 Agent Lifecycle & Typed Tool Engine.

Implements the 12-state execution lifecycle, pre-execution human approval gating,
typed tool registry, and zero-secret durable state management.
"""

from __future__ import annotations

from schemasense.agent.checkpointer import get_checkpointer
from schemasense.agent.graph import create_agent_graph
from schemasense.agent.lifecycle import (
    AgentExecutionState,
    ApprovalAction,
    ApprovalStatus,
)
from schemasense.agent.runner import (
    get_agent_run_state,
    reset_agent_runner,
    resume_agent_run,
    start_agent_run,
)
from schemasense.agent.state import (
    AgentState,
    AuditRecordEntry,
    ToolInvocationRequest,
    ToolInvocationResult,
)
from schemasense.agent.tools import (
    BaseAgentTool,
    ExecuteSafeQueryTool,
    ExecutionContext,
    InspectSchemaTool,
    ProfileColumnTool,
    ScanPIITool,
    ToolRegistry,
    ValidateSQLTool,
    clear_connection_engines,
    default_tool_registry,
    get_connection_engine,
    register_connection_engine,
    unregister_connection_engine,
)


def is_agent_lifecycle_available() -> bool:
    """Returns True if LangGraph and LangChain-Core are available in the runtime environment."""
    try:
        import langchain_core  # noqa: F401
        import langgraph  # noqa: F401

        return True
    except ImportError:
        return False


__all__ = [
    "AgentExecutionState",
    "AgentState",
    "ApprovalAction",
    "ApprovalStatus",
    "AuditRecordEntry",
    "BaseAgentTool",
    "ExecuteSafeQueryTool",
    "ExecutionContext",
    "InspectSchemaTool",
    "ProfileColumnTool",
    "ScanPIITool",
    "ToolInvocationRequest",
    "ToolInvocationResult",
    "ToolRegistry",
    "ValidateSQLTool",
    "clear_connection_engines",
    "create_agent_graph",
    "default_tool_registry",
    "get_agent_run_state",
    "get_checkpointer",
    "get_connection_engine",
    "is_agent_lifecycle_available",
    "register_connection_engine",
    "reset_agent_runner",
    "resume_agent_run",
    "start_agent_run",
    "unregister_connection_engine",
]
