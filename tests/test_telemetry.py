"""Tests for the structured telemetry and security audit logger."""

import pytest

from schemasense.telemetry import (
    TelemetryCollector,
    redact_sensitive_string,
)


@pytest.mark.unit
def test_redact_sensitive_string_masks_passwords():
    raw_url = "postgresql://user:super_secret_pw123@localhost:5432/mydb"
    masked = redact_sensitive_string(raw_url)
    assert "super_secret_pw123" not in masked
    assert "postgresql://user:***@localhost:5432/mydb" == masked


@pytest.mark.unit
def test_redact_sensitive_string_masks_key_value_pairs():
    raw_text = "Connecting with password=secret_token_abc and api_key=gemini_secret_123"
    masked = redact_sensitive_string(raw_text)
    assert "secret_token_abc" not in masked
    assert "gemini_secret_123" not in masked
    assert "password=***" in masked
    assert "api_key=***" in masked


@pytest.mark.unit
def test_telemetry_records_and_buffers_query_event():
    collector = TelemetryCollector(max_buffer_size=10)
    event = collector.record_query_execution(
        dialect="postgres",
        query="SELECT * FROM customers WHERE id = 1;",
        row_count=1,
        duration_ms=12.456,
        is_truncated=False,
    )

    assert event.event_type == "query_execution"
    assert event.details["duration_ms"] == 12.46
    assert event.details["row_count"] == 1
    assert event.details["status"] == "success"

    recent = collector.get_recent_events()
    assert len(recent) == 1
    assert recent[0] == event


@pytest.mark.unit
def test_telemetry_records_security_violation():
    collector = TelemetryCollector(max_buffer_size=5)
    event = collector.record_security_violation(
        violation_type="forbidden_dml",
        query="DROP TABLE customers;",
        reason="Drop statement forbidden",
        dialect="mysql",
    )

    assert event.event_type == "security_violation"
    assert event.details["violation_type"] == "forbidden_dml"
    assert event.details["dialect"] == "mysql"


@pytest.mark.unit
def test_telemetry_buffer_bounds_enforced():
    collector = TelemetryCollector(max_buffer_size=3)
    for i in range(5):
        collector.record_event("test_event", idx=i)

    recent = collector.get_recent_events()
    assert len(recent) == 3
    assert recent[0].details["idx"] == 2
    assert recent[-1].details["idx"] == 4
