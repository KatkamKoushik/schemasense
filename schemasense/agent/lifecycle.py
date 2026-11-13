"""Execution lifecycle states, approval statuses, and action transitions for SchemaSense 2.0."""

from __future__ import annotations

from enum import Enum


class AgentExecutionState(str, Enum):
    """The 12 formal execution states of the SchemaSense 2.0 AI Agent lifecycle."""

    RECEIVE = "receive"
    UNDERSTAND = "understand"
    PLAN = "plan"
    SELECT_TOOLS = "select_tools"
    CHECK_PERMISSIONS = "check_permissions"
    VALIDATE_PRECONDITIONS = "validate_preconditions"
    SCORE_CONFIDENCE = "score_confidence"
    HUMAN_APPROVAL = "human_approval"
    EXECUTE = "execute"
    VERIFY = "verify"
    DELIVER = "deliver"
    AUDIT_AND_LEARN = "audit_and_learn"


class ApprovalStatus(str, Enum):
    """Status of pre-execution human approval."""

    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalAction(str, Enum):
    """Actions that can be taken on a pending human approval request."""

    APPROVE = "approve"
    REJECT = "reject"
    EXPIRE = "expire"
    CANCEL = "cancel"
