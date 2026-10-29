"""Structured Telemetry & Security Audit Logging subsystem for SchemaSense."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("schemasense.telemetry")

_SECRET_PATTERNS = [
    re.compile(
        r"(password|pwd|pass|secret|token|api[_-]?key)=([^&;\s]+)", re.IGNORECASE
    ),
    re.compile(r"://([^:@/]+):([^@/]+)@", re.IGNORECASE),
]


def redact_sensitive_string(raw: str) -> str:
    """Masks database passwords, auth tokens, and connection credentials."""
    if not raw:
        return ""
    masked = raw
    masked = _SECRET_PATTERNS[0].sub(r"\1=***", masked)
    masked = _SECRET_PATTERNS[1].sub(r"://\1:***@", masked)
    return masked


def redact_sql_literals(sql: str) -> str:
    """
    Scrubs sensitive user literals (PII, names, passwords, amounts) from SQL query strings.
    Replaces string literals ('...') and numeric constants in predicates with '?'.
    """
    if not sql:
        return ""
    # 1. Replace single-quoted string literals with '?'
    scrubbed = re.sub(r"'(?:''|[^'])*'", "'?'", sql)
    # 2. Replace numeric literals in predicates and assignments
    scrubbed = re.sub(
        r"(?<=[=><!,\s(])\b\d+(?:\.\d+)?\b(?=[=><!,\s);]|$)", "?", scrubbed
    )
    return scrubbed


def compute_query_fingerprint(sql: str) -> str:
    """
    Computes a deterministic SHA-256 fingerprint from normalized, literal-scrubbed SQL.
    Enables aggregated query-frequency and performance analytics without storing raw PII.
    """
    if not sql:
        return ""
    redacted = redact_sql_literals(sql)
    normalized = " ".join(redacted.split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class TelemetryEvent:
    event_type: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class TelemetryCollector:
    """Collects and audits operational events, security rejections, and model latency."""

    def __init__(self, max_buffer_size: int = 1000):
        self._buffer: list[TelemetryEvent] = []
        self._max_buffer_size = max_buffer_size

    def record_event(self, event_type: str, **kwargs: Any) -> TelemetryEvent:
        clean_details = {}
        for k, v in kwargs.items():
            if isinstance(v, str):
                clean_details[k] = redact_sensitive_string(v)
            else:
                clean_details[k] = v

        event = TelemetryEvent(event_type=event_type, details=clean_details)
        if len(self._buffer) >= self._max_buffer_size:
            self._buffer.pop(0)
        self._buffer.append(event)

        logger.info(event.to_json())
        return event

    def record_query_execution(
        self,
        dialect: str,
        query: str,
        row_count: int,
        duration_ms: float,
        is_truncated: bool,
        error: str | None = None,
    ) -> TelemetryEvent:
        redacted_sql = redact_sql_literals(query)
        fingerprint = compute_query_fingerprint(query)
        return self.record_event(
            event_type="query_execution",
            dialect=dialect,
            query=redacted_sql,
            query_fingerprint=fingerprint,
            row_count=row_count,
            duration_ms=round(duration_ms, 2),
            is_truncated=is_truncated,
            status="error" if error else "success",
            error=error,
        )

    def record_security_violation(
        self,
        violation_type: str,
        query: str,
        reason: str,
        dialect: str,
    ) -> TelemetryEvent:
        redacted_sql = redact_sql_literals(query)
        fingerprint = compute_query_fingerprint(query)
        return self.record_event(
            event_type="security_violation",
            violation_type=violation_type,
            query=redacted_sql,
            query_fingerprint=fingerprint,
            reason=reason,
            dialect=dialect,
        )

    def record_ai_inference(
        self,
        backend_id: str,
        model_name: str,
        latency_ms: float,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        status: str = "success",
        error: str | None = None,
    ) -> TelemetryEvent:
        return self.record_event(
            event_type="ai_inference",
            backend_id=backend_id,
            model_name=model_name,
            latency_ms=round(latency_ms, 2),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            status=status,
            error=error,
        )

    def get_recent_events(self, limit: int = 50) -> list[TelemetryEvent]:
        return list(self._buffer[-limit:])


# Global process singleton
telemetry = TelemetryCollector()
