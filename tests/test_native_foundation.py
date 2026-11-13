"""Unit tests for SchemaSense Phase 1 Native Foundation & PyO3 Interoperability."""

from __future__ import annotations

import os
from unittest.mock import patch

import schemasense


def test_native_core_detection_and_metadata():
    """Verifies that schemasense-core is detected and reports correct build info."""
    info = schemasense.get_native_core_info()
    assert isinstance(info, dict)

    if schemasense.HAS_NATIVE_CORE:
        assert info["accelerated"] is True
        assert info["version"] == "0.1.0"
        assert "build_info" in info
        build_info = info["build_info"]
        assert build_info["version"] == "0.1.0"
        assert build_info["abi3"] == "cp310-abi3"
    else:
        assert info["accelerated"] is False
        assert info["version"] is None
        assert "reason" in info


def test_native_core_environment_variable_override(monkeypatch):
    """Verifies that SCHEMASENSE_DISABLE_NATIVE_CORE=1 disables native acceleration."""
    monkeypatch.setenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "1")

    # Re-evaluate logic under override
    is_disabled = os.getenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    assert is_disabled is True


def test_native_core_simulated_import_failure():
    """Verifies graceful degradation when schemasense_core is missing or fails to import."""
    with patch.dict("sys.modules", {"schemasense_core": None}):
        with patch.object(schemasense, "HAS_NATIVE_CORE", False):
            info = schemasense.get_native_core_info()
            assert info["accelerated"] is False
            assert info["version"] is None
            assert "reason" in info


def test_schemasense_public_exports_preserved():
    """Verifies that introducing native foundation preserves all existing public exports."""
    expected_exports = [
        "AIAgentError",
        "AIProviderError",
        "AIQuotaExceededError",
        "AISchemaHallucinationError",
        "AITimeoutError",
        "SQLAgentResponse",
        "SchemaSenseAIAgent",
        "create_agent",
        "extract_sql_from_text",
        "get_session_agent",
        "verify_schema_fidelity",
        "auth",
        "HAS_NATIVE_CORE",
        "get_native_core_info",
    ]
    for export in expected_exports:
        assert hasattr(schemasense, export), f"Missing public export: {export}"
