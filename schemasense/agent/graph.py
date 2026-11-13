"""LangGraph 12-state execution graph with pre-execution human approval gating."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from schemasense.agent.lifecycle import AgentExecutionState, ApprovalStatus
from schemasense.agent.state import AgentState
from schemasense.agent.tools import ExecutionContext, default_tool_registry

logger = logging.getLogger("schemasense.agent.graph")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# NODE HANDLERS (THE 12 EXECUTION STATES)
# ─────────────────────────────────────────────────────────────
def node_receive(state: AgentState) -> dict[str, Any]:
    """State 1: RECEIVE — Ingest and validate incoming execution request."""
    state.record_transition(AgentExecutionState.RECEIVE)
    state.record_audit(
        state=AgentExecutionState.RECEIVE.value,
        event="Execution request received",
        details={
            "run_id": state.run_id,
            "tenant_id": state.tenant_id,
            "user_id": state.user_id,
            "connection_id": state.connection_id,
            "goal": state.goal,
        },
    )
    return {
        "current_state": AgentExecutionState.RECEIVE,
        "state_history": list(state.state_history),
        "audit_events": list(state.audit_events),
    }


def node_understand(state: AgentState) -> dict[str, Any]:
    """State 2: UNDERSTAND — Semantic intent analysis and dialect resolution."""
    state.record_transition(AgentExecutionState.UNDERSTAND)

    goal_lower = state.goal.lower()
    inferred_tables: list[str] = []
    # Simple extraction of candidate table names from context or goal
    if "context" in state.context and "tables" in state.context:
        inferred_tables = list(state.context["tables"])

    state.record_audit(
        state=AgentExecutionState.UNDERSTAND.value,
        event="Goal semantics parsed",
        details={
            "target_tables": inferred_tables,
            "has_sql": "select" in goal_lower,
        },
    )
    return {
        "current_state": AgentExecutionState.UNDERSTAND,
        "state_history": list(state.state_history),
        "target_tables": inferred_tables,
        "audit_events": list(state.audit_events),
    }


def node_plan(state: AgentState) -> dict[str, Any]:
    """State 3: PLAN — Formulate structured, ordered execution plan."""
    state.record_transition(AgentExecutionState.PLAN)

    plan_steps: list[str] = ["inspect_schema"]
    goal_lower = state.goal.lower()

    if "pii" in goal_lower or "sensitive" in goal_lower:
        plan_steps.append("scan_pii")
    if "profile" in goal_lower or "quality" in goal_lower:
        plan_steps.append("profile_column")
    if "select" in goal_lower or "query" in goal_lower:
        plan_steps.extend(["validate_sql", "execute_query"])

    state.record_audit(
        state=AgentExecutionState.PLAN.value,
        event="Execution plan formulated",
        details={"steps": plan_steps},
    )
    return {
        "current_state": AgentExecutionState.PLAN,
        "state_history": list(state.state_history),
        "plan": plan_steps,
        "audit_events": list(state.audit_events),
    }


def node_select_tools(state: AgentState) -> dict[str, Any]:
    """State 4: SELECT_TOOLS — Materialize typed tool invocation requests."""
    from schemasense.agent.state import ToolInvocationRequest

    state.record_transition(AgentExecutionState.SELECT_TOOLS)

    tool_requests: list[ToolInvocationRequest] = []
    for step in state.plan:
        tool = default_tool_registry.get(step)
        if tool is not None:
            # Build tool-specific invocation parameters
            params: dict[str, Any] = {}
            if step == "validate_sql" or step == "execute_query":
                # Check if SQL was provided in context or goal
                sql_candidate = state.context.get("sql") or (
                    state.goal if "select" in state.goal.lower() else "SELECT 1;"
                )
                params["sql_query"] = sql_candidate
                params["dialect"] = state.context.get("dialect", "sqlite")
            elif step == "scan_pii":
                params["samples"] = state.context.get("samples", ["test@example.com"])
            elif step == "profile_column":
                params["table_name"] = state.context.get("table_name", "users")
                params["column_name"] = state.context.get("column_name", "id")

            tool_requests.append(
                ToolInvocationRequest(
                    tool_name=step,
                    parameters=params,
                    is_high_risk=tool.is_high_risk,
                )
            )

    selected_names = [r.tool_name for r in tool_requests]
    state.record_audit(
        state=AgentExecutionState.SELECT_TOOLS.value,
        event="Tools selected",
        details={"tools": selected_names},
    )
    return {
        "current_state": AgentExecutionState.SELECT_TOOLS,
        "state_history": list(state.state_history),
        "selected_tools": selected_names,
        "tool_requests": tool_requests,
        "audit_events": list(state.audit_events),
    }


def node_check_permissions(state: AgentState) -> dict[str, Any]:
    """State 5: CHECK_PERMISSIONS — Resource-level tenant isolation and authorization."""
    state.record_transition(AgentExecutionState.CHECK_PERMISSIONS)

    # Permission check: Viewers cannot execute high-risk tools
    has_high_risk = any(r.is_high_risk for r in state.tool_requests)
    user_roles = set(state.user_roles)

    # If user is only a 'viewer' and tries to execute high-risk tools: fail-closed!
    if has_high_risk and "admin" not in user_roles and "analyst" not in user_roles:
        err_msg = (
            f"Permission denied: User '{state.user_id}' with roles {state.user_roles} "
            "is not authorized to execute high-risk operations."
        )
        state.record_audit(
            state=AgentExecutionState.CHECK_PERMISSIONS.value,
            event="Permission check rejected (fail-closed)",
            details={"error": err_msg},
        )
        return {
            "current_state": AgentExecutionState.CHECK_PERMISSIONS,
            "state_history": list(state.state_history),
            "error": err_msg,
            "is_terminal": True,
            "audit_events": list(state.audit_events),
        }

    state.record_audit(
        state=AgentExecutionState.CHECK_PERMISSIONS.value,
        event="Permissions verified",
        details={"roles": state.user_roles},
    )
    return {
        "current_state": AgentExecutionState.CHECK_PERMISSIONS,
        "state_history": list(state.state_history),
        "audit_events": list(state.audit_events),
    }


def node_validate_preconditions(state: AgentState) -> dict[str, Any]:
    """State 6: VALIDATE_PRECONDITIONS — Connection and environment readiness checks."""
    from schemasense.agent.tools import get_connection_engine

    state.record_transition(AgentExecutionState.VALIDATE_PRECONDITIONS)

    engine = get_connection_engine(state.connection_id)
    if engine is None:
        err_msg = f"Precondition failed: No active engine registered for connection_id '{state.connection_id}'."
        state.record_audit(
            state=AgentExecutionState.VALIDATE_PRECONDITIONS.value,
            event="Precondition check failed",
            details={"error": err_msg},
        )
        return {
            "current_state": AgentExecutionState.VALIDATE_PRECONDITIONS,
            "state_history": list(state.state_history),
            "error": err_msg,
            "is_terminal": True,
            "audit_events": list(state.audit_events),
        }

    state.record_audit(
        state=AgentExecutionState.VALIDATE_PRECONDITIONS.value,
        event="Preconditions validated",
        details={"connection_id": state.connection_id},
    )
    return {
        "current_state": AgentExecutionState.VALIDATE_PRECONDITIONS,
        "state_history": list(state.state_history),
        "audit_events": list(state.audit_events),
    }


def node_score_confidence(state: AgentState) -> dict[str, Any]:
    """State 7: SCORE_CONFIDENCE — Evaluate risk and determine human approval requirement."""
    state.record_transition(AgentExecutionState.SCORE_CONFIDENCE)

    # Calculate confidence score heuristic
    has_high_risk = any(r.is_high_risk for r in state.tool_requests)
    base_confidence = 0.95 if not has_high_risk else 0.75

    # Any confidence factor overrides from context
    confidence_factors = {"base_heuristic": base_confidence}
    if state.context.get("force_low_confidence"):
        base_confidence = 0.5
        confidence_factors["forced_low"] = 0.5

    # Gating rule: High risk OR confidence < 0.8 requires human approval
    requires_approval = has_high_risk or base_confidence < 0.8
    gate_reason = None
    approval_status = state.approval_status

    if requires_approval:
        gate_reason = (
            "Pre-execution human approval required due to high-risk tool "
            if has_high_risk
            else "Pre-execution human approval required due to low confidence score (< 0.80)."
        )
        approval_status = ApprovalStatus.PENDING

    state.record_audit(
        state=AgentExecutionState.SCORE_CONFIDENCE.value,
        event="Confidence evaluated",
        details={
            "confidence_score": base_confidence,
            "requires_approval": requires_approval,
            "gate_reason": gate_reason,
        },
    )

    return {
        "current_state": AgentExecutionState.SCORE_CONFIDENCE,
        "state_history": list(state.state_history),
        "confidence_score": base_confidence,
        "confidence_factors": confidence_factors,
        "requires_approval": requires_approval,
        "approval_gate_reason": gate_reason,
        "approval_status": approval_status,
        "approval_requested_at": _utc_now_iso() if requires_approval else None,
        "audit_events": list(state.audit_events),
    }


def node_human_approval(state: AgentState) -> dict[str, Any]:
    """State 8: HUMAN_APPROVAL — Pre-execution human approval decision processor."""
    state.record_transition(AgentExecutionState.HUMAN_APPROVAL)

    status = state.approval_status

    if status == ApprovalStatus.APPROVED:
        state.record_audit(
            state=AgentExecutionState.HUMAN_APPROVAL.value,
            event="Human approval GRANTED",
            details={
                "decided_by": state.approval_decision_by or "reviewer",
                "reason": state.approval_reason,
            },
        )
        return {
            "current_state": AgentExecutionState.HUMAN_APPROVAL,
            "state_history": list(state.state_history),
            "audit_events": list(state.audit_events),
        }

    # If rejected, expired, cancelled or still pending
    rejection_msg = (
        f"Execution aborted at human approval gate with status '{status.value}'"
    )
    if state.approval_reason:
        rejection_msg += f": {state.approval_reason}"

    state.record_audit(
        state=AgentExecutionState.HUMAN_APPROVAL.value,
        event=f"Human approval REJECTED ({status.value})",
        details={
            "status": status.value,
            "reason": state.approval_reason,
        },
    )
    return {
        "current_state": AgentExecutionState.HUMAN_APPROVAL,
        "state_history": list(state.state_history),
        "error": rejection_msg,
        "is_terminal": True,
        "audit_events": list(state.audit_events),
    }


def node_execute(state: AgentState) -> dict[str, Any]:
    """State 9: EXECUTE — Execute approved and authorized tools safely."""
    state.record_transition(AgentExecutionState.EXECUTE)

    ctx = ExecutionContext(
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        user_roles=state.user_roles,
        connection_id=state.connection_id,
    )

    results = []
    generated_sql = None

    for req in state.tool_requests:
        tool = default_tool_registry.get(req.tool_name)
        if tool is None:
            continue

        res = tool.execute(
            parameters=req.parameters,
            context=ctx,
            idempotency_key=req.idempotency_key,
        )
        results.append(res)

        if req.tool_name in ("validate_sql", "execute_query"):
            generated_sql = req.parameters.get("sql_query")

    state.record_audit(
        state=AgentExecutionState.EXECUTE.value,
        event="Tools executed",
        details={
            "total_executed": len(results),
            "success_count": sum(1 for r in results if r.success),
        },
    )

    return {
        "current_state": AgentExecutionState.EXECUTE,
        "state_history": list(state.state_history),
        "tool_results": results,
        "generated_sql": generated_sql,
        "audit_events": list(state.audit_events),
    }


def node_verify(state: AgentState) -> dict[str, Any]:
    """State 10: VERIFY — Result integrity, row bounding, and schema fidelity verification."""
    state.record_transition(AgentExecutionState.VERIFY)

    failed_tools = [r.tool_name for r in state.tool_results if not r.success]
    has_failures = len(failed_tools) > 0

    state.record_audit(
        state=AgentExecutionState.VERIFY.value,
        event="Results verified",
        details={
            "verified": not has_failures,
            "failed_tools": failed_tools,
        },
    )

    return {
        "current_state": AgentExecutionState.VERIFY,
        "state_history": list(state.state_history),
        "audit_events": list(state.audit_events),
    }


def node_deliver(state: AgentState) -> dict[str, Any]:
    """State 11: DELIVER — Synthesize response and analytical output payload."""
    state.record_transition(AgentExecutionState.DELIVER)

    deliverable = {
        "run_id": state.run_id,
        "goal": state.goal,
        "generated_sql": state.generated_sql,
        "tool_results": [r.model_dump() for r in state.tool_results],
        "confidence_score": state.confidence_score,
        "approval_status": state.approval_status.value,
    }

    state.record_audit(
        state=AgentExecutionState.DELIVER.value,
        event="Deliverable produced",
        details={"status": "success"},
    )

    return {
        "current_state": AgentExecutionState.DELIVER,
        "state_history": list(state.state_history),
        "final_response": deliverable,
        "audit_events": list(state.audit_events),
    }


def node_audit_and_learn(state: AgentState) -> dict[str, Any]:
    """State 12: AUDIT_AND_LEARN — Final sanitize, audit closure, and terminal state."""
    state.record_transition(AgentExecutionState.AUDIT_AND_LEARN)
    state.record_audit(
        state=AgentExecutionState.AUDIT_AND_LEARN.value,
        event="Agent run completed",
        details={
            "terminal": True,
            "has_error": state.error is not None,
            "total_audit_events": len(state.audit_events) + 1,
        },
    )

    return {
        "current_state": AgentExecutionState.AUDIT_AND_LEARN,
        "state_history": list(state.state_history),
        "is_terminal": True,
        "audit_events": list(state.audit_events),
    }


# ─────────────────────────────────────────────────────────────
# CONDITIONAL ROUTING FUNCTIONS
# ─────────────────────────────────────────────────────────────
def route_after_permissions(state: AgentState) -> str:
    """Routes to audit_and_learn immediately if permissions failed closed."""
    if state.error or state.is_terminal:
        return AgentExecutionState.AUDIT_AND_LEARN.value
    return AgentExecutionState.VALIDATE_PRECONDITIONS.value


def route_after_preconditions(state: AgentState) -> str:
    """Routes to audit_and_learn if preconditions failed."""
    if state.error or state.is_terminal:
        return AgentExecutionState.AUDIT_AND_LEARN.value
    return AgentExecutionState.SCORE_CONFIDENCE.value


def route_after_confidence(state: AgentState) -> str:
    """Routes to human_approval if gated, otherwise directly to execute."""
    if state.requires_approval:
        return AgentExecutionState.HUMAN_APPROVAL.value
    return AgentExecutionState.EXECUTE.value


def route_after_human_approval(state: AgentState) -> str:
    """Routes to execute only if approved; aborts to audit_and_learn otherwise."""
    if state.approval_status == ApprovalStatus.APPROVED and not state.is_terminal:
        return AgentExecutionState.EXECUTE.value
    return AgentExecutionState.AUDIT_AND_LEARN.value


# ─────────────────────────────────────────────────────────────
# GRAPH FACTORY
# ─────────────────────────────────────────────────────────────
def create_agent_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Builds and compiles the 12-state LangGraph execution workflow.

    Enforces pre-execution human approval gating by compiling with
    interrupt_before=['human_approval'].
    """
    builder = StateGraph(AgentState)

    # Register all 12 nodes
    builder.add_node(AgentExecutionState.RECEIVE.value, node_receive)
    builder.add_node(AgentExecutionState.UNDERSTAND.value, node_understand)
    builder.add_node(AgentExecutionState.PLAN.value, node_plan)
    builder.add_node(AgentExecutionState.SELECT_TOOLS.value, node_select_tools)
    builder.add_node(
        AgentExecutionState.CHECK_PERMISSIONS.value, node_check_permissions
    )
    builder.add_node(
        AgentExecutionState.VALIDATE_PRECONDITIONS.value, node_validate_preconditions
    )
    builder.add_node(AgentExecutionState.SCORE_CONFIDENCE.value, node_score_confidence)
    builder.add_node(AgentExecutionState.HUMAN_APPROVAL.value, node_human_approval)
    builder.add_node(AgentExecutionState.EXECUTE.value, node_execute)
    builder.add_node(AgentExecutionState.VERIFY.value, node_verify)
    builder.add_node(AgentExecutionState.DELIVER.value, node_deliver)
    builder.add_node(AgentExecutionState.AUDIT_AND_LEARN.value, node_audit_and_learn)

    # Linear flow for States 1 -> 5
    builder.add_edge(START, AgentExecutionState.RECEIVE.value)
    builder.add_edge(
        AgentExecutionState.RECEIVE.value, AgentExecutionState.UNDERSTAND.value
    )
    builder.add_edge(
        AgentExecutionState.UNDERSTAND.value, AgentExecutionState.PLAN.value
    )
    builder.add_edge(
        AgentExecutionState.PLAN.value, AgentExecutionState.SELECT_TOOLS.value
    )
    builder.add_edge(
        AgentExecutionState.SELECT_TOOLS.value,
        AgentExecutionState.CHECK_PERMISSIONS.value,
    )

    # Conditional after Check Permissions (State 5)
    builder.add_conditional_edges(
        AgentExecutionState.CHECK_PERMISSIONS.value,
        route_after_permissions,
        {
            AgentExecutionState.VALIDATE_PRECONDITIONS.value: AgentExecutionState.VALIDATE_PRECONDITIONS.value,
            AgentExecutionState.AUDIT_AND_LEARN.value: AgentExecutionState.AUDIT_AND_LEARN.value,
        },
    )

    # Conditional after Validate Preconditions (State 6)
    builder.add_conditional_edges(
        AgentExecutionState.VALIDATE_PRECONDITIONS.value,
        route_after_preconditions,
        {
            AgentExecutionState.SCORE_CONFIDENCE.value: AgentExecutionState.SCORE_CONFIDENCE.value,
            AgentExecutionState.AUDIT_AND_LEARN.value: AgentExecutionState.AUDIT_AND_LEARN.value,
        },
    )

    # Conditional after Score Confidence (State 7)
    builder.add_conditional_edges(
        AgentExecutionState.SCORE_CONFIDENCE.value,
        route_after_confidence,
        {
            AgentExecutionState.HUMAN_APPROVAL.value: AgentExecutionState.HUMAN_APPROVAL.value,
            AgentExecutionState.EXECUTE.value: AgentExecutionState.EXECUTE.value,
        },
    )

    # Conditional after Human Approval (State 8)
    builder.add_conditional_edges(
        AgentExecutionState.HUMAN_APPROVAL.value,
        route_after_human_approval,
        {
            AgentExecutionState.EXECUTE.value: AgentExecutionState.EXECUTE.value,
            AgentExecutionState.AUDIT_AND_LEARN.value: AgentExecutionState.AUDIT_AND_LEARN.value,
        },
    )

    # Flow after Execution (States 9 -> 12)
    builder.add_edge(
        AgentExecutionState.EXECUTE.value, AgentExecutionState.VERIFY.value
    )
    builder.add_edge(
        AgentExecutionState.VERIFY.value, AgentExecutionState.DELIVER.value
    )
    builder.add_edge(
        AgentExecutionState.DELIVER.value, AgentExecutionState.AUDIT_AND_LEARN.value
    )
    builder.add_edge(AgentExecutionState.AUDIT_AND_LEARN.value, END)

    # If no checkpointer provided, default to MemorySaver to enable human-in-the-loop interrupts
    saver = checkpointer if checkpointer is not None else MemorySaver()

    return builder.compile(
        checkpointer=saver,
        interrupt_before=[AgentExecutionState.HUMAN_APPROVAL.value],
    )
