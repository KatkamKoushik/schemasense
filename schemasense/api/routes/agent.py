"""FastAPI routes for Agent lifecycle management, approval gating, and sequenced SSE streaming."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from schemasense.agent import (
    ApprovalAction,
    get_agent_run_state,
    resume_agent_run,
)
from schemasense.api.auth import get_current_identity
from schemasense.api.events import get_event_store
from schemasense.api.schemas import (
    AgentRunCreateRequest,
    AgentRunDetailResponse,
    AgentRunSummaryResponse,
    AsyncProfilingRequest,
    AuthenticatedIdentity,
    HumanApprovalActionRequest,
    ProfilingTaskResponse,
)
from schemasense.config import resolve_connection_reference
from schemasense.tasks import QueueUnavailableError, TaskDispatcher

logger = logging.getLogger("schemasense.api.routes.agent")

router = APIRouter(prefix="/agent", tags=["Agent Orchestration"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post(
    "/runs",
    response_model=AgentRunSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate Agent Lifecycle Run",
)
async def create_agent_run(
    request: AgentRunCreateRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> AgentRunSummaryResponse:
    """Initiates an agent execution run with verified server-side identity and connection resolution.

    Client-provided identity fields are completely ignored; user_id, tenant_id,
    and roles are derived strictly from the cryptographic auth context.
    """
    # 1. Enforce tenant-scoped connection authorization
    try:
        resolve_connection_reference(
            request.connection_id,
            requesting_tenant_id=identity.tenant_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection reference '{request.connection_id}' not found.",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    now = _utc_now_iso()
    idempotency_key = request.parameters.get("idempotency_key")

    # 2. Dispatch task via Dual-Mode task dispatcher
    try:
        TaskDispatcher.dispatch_agent_run(
            run_id=run_id,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            connection_id=request.connection_id,
            goal=request.prompt,
            user_roles=identity.roles,
            context=request.parameters,
            idempotency_key=idempotency_key,
        )
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return AgentRunSummaryResponse(
        run_id=run_id,
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        connection_id=request.connection_id,
        current_state="receive",
        created_at=now,
        updated_at=now,
        event_stream_url=f"/api/v1/agent/runs/{run_id}/events",
    )


@router.get(
    "/runs/{run_id}",
    response_model=AgentRunDetailResponse,
    summary="Get Agent Run State",
)
async def get_agent_run(
    run_id: str,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> AgentRunDetailResponse:
    """Retrieves full execution details and state transitions for a run."""
    state = get_agent_run_state(run_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent run '{run_id}' not found.",
        )

    # Cross-tenant isolation verification
    if state.tenant_id != identity.tenant_id and not identity.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Run belongs to a different tenant context.",
        )

    now = _utc_now_iso()
    return AgentRunDetailResponse(
        run_id=state.run_id,
        tenant_id=state.tenant_id,
        user_id=state.user_id,
        connection_id=state.connection_id,
        goal=state.goal,
        current_state=state.current_state.value,
        state_history=state.state_history,
        requires_approval=state.requires_approval,
        approval_status=state.approval_status.value,
        approval_gate_reason=state.approval_gate_reason,
        approval_decision_by=state.approval_decision_by,
        confidence_score=state.confidence_score,
        generated_sql=state.generated_sql,
        tool_results=[r.model_dump() for r in state.tool_results],
        final_response=state.final_response,
        error=state.error,
        is_terminal=state.is_terminal,
        event_stream_url=f"/api/v1/agent/runs/{run_id}/events",
        created_at=now,
        updated_at=now,
    )


@router.post(
    "/runs/{run_id}/approval",
    response_model=AgentRunDetailResponse,
    summary="Submit Human Approval Decision",
)
async def submit_approval_decision(
    run_id: str,
    request: HumanApprovalActionRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> AgentRunDetailResponse:
    """Processes a human approval decision (APPROVE, REJECT, CANCEL, EXPIRE) on a gated run."""
    # Enforce role-based permission: only admin and analyst can decide
    if not identity.is_admin and "analyst" not in identity.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only analysts or admins are authorized to grant or reject execution approvals.",
        )

    state = get_agent_run_state(run_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent run '{run_id}' not found.",
        )

    # Cross-tenant isolation
    if state.tenant_id != identity.tenant_id and not identity.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Run belongs to a different tenant context.",
        )

    action_enum = ApprovalAction(request.action)
    resumed_state = resume_agent_run(
        run_id=run_id,
        action=action_enum,
        actor=identity.user_id,
        reason=request.comment,
    )

    event_store = get_event_store()
    event_store.record_event(
        run_id=run_id,
        event_type="approval_decision",
        data={
            "action": request.action,
            "decision_by": identity.user_id,
            "reason": request.comment,
        },
    )

    if resumed_state.is_terminal:
        if resumed_state.error:
            event_store.record_event(
                run_id=run_id,
                event_type="run_failed",
                data={"error": resumed_state.error, "run_id": run_id},
            )
        else:
            event_store.record_event(
                run_id=run_id,
                event_type="run_completed",
                data={
                    "run_id": run_id,
                    "confidence_score": resumed_state.confidence_score,
                    "has_deliverable": resumed_state.final_response is not None,
                },
            )
        event_store.close_stream(run_id)

    now = _utc_now_iso()
    return AgentRunDetailResponse(
        run_id=resumed_state.run_id,
        tenant_id=resumed_state.tenant_id,
        user_id=resumed_state.user_id,
        connection_id=resumed_state.connection_id,
        goal=resumed_state.goal,
        current_state=resumed_state.current_state.value,
        state_history=resumed_state.state_history,
        requires_approval=resumed_state.requires_approval,
        approval_status=resumed_state.approval_status.value,
        approval_gate_reason=resumed_state.approval_gate_reason,
        approval_decision_by=resumed_state.approval_decision_by,
        confidence_score=resumed_state.confidence_score,
        generated_sql=resumed_state.generated_sql,
        tool_results=[r.model_dump() for r in resumed_state.tool_results],
        final_response=resumed_state.final_response,
        error=resumed_state.error,
        is_terminal=resumed_state.is_terminal,
        event_stream_url=f"/api/v1/agent/runs/{run_id}/events",
        created_at=now,
        updated_at=now,
    )


@router.get(
    "/runs/{run_id}/events",
    summary="Sequenced SSE Event Stream with Replay",
)
async def stream_agent_events(
    run_id: str,
    last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
    last_event_id_query: int = Query(0, alias="last_event_id"),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> StreamingResponse:
    """Streams sequenced Server-Sent Events with reconnection replay support.

    If Last-Event-ID header (or query param) is present, replays all missed events
    before streaming live progress frames.
    """
    # Parse last event ID (header takes precedence)
    since_id = 0
    if last_event_id_header and last_event_id_header.isdigit():
        since_id = int(last_event_id_header)
    elif last_event_id_query > 0:
        since_id = last_event_id_query

    event_store = get_event_store()

    return StreamingResponse(
        event_store.subscribe(run_id=run_id, since_id=since_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/profiling",
    response_model=ProfilingTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate Asynchronous Schema Profiling",
)
async def create_profiling_task(
    request: AsyncProfilingRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> ProfilingTaskResponse:
    """Dispatches background schema profiling and quality inspection."""
    # Enforce tenant-scoped connection authorization
    try:
        resolve_connection_reference(
            request.connection_id,
            requesting_tenant_id=identity.tenant_id,
        )
    except (KeyError, PermissionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    try:
        task_id = TaskDispatcher.dispatch_profiling(
            connection_id=request.connection_id,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            table_names=request.table_names,
            idempotency_key=request.idempotency_key,
        )
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return ProfilingTaskResponse(
        task_id=task_id,
        connection_id=request.connection_id,
        tenant_id=identity.tenant_id,
        status="completed" if task_id.startswith("sync_") else "queued",
        table_count=len(request.table_names) if request.table_names else 0,
        message="Profiling job accepted and processed.",
    )
