"""API Routes Registry for SchemaSense 2.0."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from schemasense.api.auth import get_current_identity
from schemasense.api.routes.health import router as health_router
from schemasense.api.schemas import (
    AgentRunCreateRequest,
    AgentRunSummaryResponse,
    AuthenticatedIdentity,
)
from schemasense.config import resolve_connection_reference

router = APIRouter()

# Mount health & diagnostic probes
router.include_router(health_router)


@router.post(
    "/agent/runs",
    response_model=AgentRunSummaryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Agent Run (Authenticated)",
    tags=["Agent Orchestration"],
)
async def create_agent_run(
    request: AgentRunCreateRequest,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
) -> AgentRunSummaryResponse:
    """Initiates an agent run using verified server-side identity and connection_id.

    Client-provided identity fields are completely ignored; user_id and tenant_id
    are strictly extracted from the cryptographic auth context.
    """
    # Verify the connection reference is accessible to the caller's tenant
    resolve_connection_reference(
        request.connection_id,
        requesting_tenant_id=identity.tenant_id,
    )

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    return AgentRunSummaryResponse(
        run_id=run_id,
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        connection_id=request.connection_id,
        current_state="receive",
        created_at=now,
        updated_at=now,
    )
