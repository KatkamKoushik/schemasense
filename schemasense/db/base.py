"""SQLAlchemy 2.0 Base and Mixins for SchemaSense 2.0 Platform State."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for all SchemaSense 2.0 platform entities."""

    def to_dict_safe(self) -> dict[str, Any]:
        """Returns a sanitized dictionary representation excluding sensitive attributes."""
        result: dict[str, Any] = {}
        for col in self.__table__.columns:
            val = getattr(self, col.name)
            # Serialize datetimes to ISO8601 strings
            if isinstance(val, datetime):
                val = val.isoformat()
            # Explicitly redact any column that might carry credentials
            if "secret" in col.name or "password" in col.name or "token" in col.name:
                val = "***REDACTED***"
            result[col.name] = val
        return result


def generate_uuid() -> str:
    """Generates a standard 32-character hex UUID string."""
    return uuid.uuid4().hex


class TimestampMixin:
    """Provides UTC creation and update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TenantScopedMixin:
    """Enforces multi-tenant isolation by binding rows to a tenant_id."""

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
        default="default",
    )
