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


@pytest.mark.unit
def test_redact_sql_literals_and_fingerprinting():
    """Verifies that SQL strings, PII, and numbers are scrubbed into ? with deterministic fingerprints."""
    from schemasense.telemetry import compute_query_fingerprint, redact_sql_literals

    raw_sql1 = (
        "SELECT * FROM users WHERE email = 'ceo@enterprise.com' AND salary > 250000;"
    )
    raw_sql2 = "SELECT * FROM users WHERE email = 'dev@startup.io' AND salary > 80000;"

    scrubbed1 = redact_sql_literals(raw_sql1)
    scrubbed2 = redact_sql_literals(raw_sql2)

    assert "ceo@enterprise.com" not in scrubbed1
    assert "250000" not in scrubbed1
    assert "dev@startup.io" not in scrubbed2
    assert "80000" not in scrubbed2

    assert "email = '?'" in scrubbed1
    assert "salary > ?" in scrubbed1

    # Deterministic fingerprint matching across literal variations
    fp1 = compute_query_fingerprint(raw_sql1)
    fp2 = compute_query_fingerprint(raw_sql2)
    assert len(fp1) == 64  # SHA-256
    assert fp1 == fp2  # Identical query templates have identical fingerprints
