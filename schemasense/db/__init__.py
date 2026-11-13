"""SchemaSense 2.0 Platform Database Layer."""

from __future__ import annotations

from schemasense.db.base import Base
from schemasense.db.models import (
    AgentRunRecord,
    ApiKey,
    AuditEventRecord,
    BenchmarkEvaluationRecord,
    ConnectionReference,
    Tenant,
    User,
)
from schemasense.db.session import (
    create_all_tables,
    drop_all_tables,
    get_db,
    get_engine,
    get_session_factory,
)

__all__ = [
    "Base",
    "Tenant",
    "User",
    "ApiKey",
    "ConnectionReference",
    "AgentRunRecord",
    "AuditEventRecord",
    "BenchmarkEvaluationRecord",
    "get_engine",
    "get_session_factory",
    "get_db",
    "create_all_tables",
    "drop_all_tables",
]
