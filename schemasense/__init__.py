"""SchemaSense AI — Secure Database Intelligence & Analytics Engine."""

from __future__ import annotations

import importlib.util
import os
from typing import Any

from schemasense import auth
from schemasense.ai_agent import (
    AIAgentError,
    AIProviderError,
    AIQuotaExceededError,
    AISchemaHallucinationError,
    AITimeoutError,
    SchemaSenseAIAgent,
    SQLAgentResponse,
    create_agent,
    extract_sql_from_text,
    get_session_agent,
    verify_schema_fidelity,
)

__version__ = "1.0.0"

# Native Rust Acceleration Core (Optional)
# If schemasense-core is installed and not explicitly disabled via SCHEMASENSE_DISABLE_NATIVE_CORE=1,
# native acceleration is activated. Otherwise, pure-Python fallbacks are strictly maintained.
if os.getenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "0").lower() in ("1", "true", "yes"):
    HAS_NATIVE_CORE = False
    _native_core_error: str | None = (
        "Native acceleration disabled via SCHEMASENSE_DISABLE_NATIVE_CORE."
    )
else:
    if importlib.util.find_spec("schemasense_core") is not None:
        try:
            import schemasense_core  # type: ignore[import-untyped] # noqa: F401

            HAS_NATIVE_CORE = True
            _native_core_error = None
        except ImportError as _err:
            HAS_NATIVE_CORE = False
            _native_core_error = str(_err)
    else:
        HAS_NATIVE_CORE = False
        _native_core_error = "schemasense-core package not installed."


def is_native_core_available() -> bool:
    """Returns True if schemasense-core is installed and not dynamically disabled via environment."""
    if os.getenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "0").lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    return HAS_NATIVE_CORE


def get_native_core_info() -> dict[str, Any]:
    """Returns diagnostic information regarding the presence and build of the native Rust core."""
    if not is_native_core_available():
        reason = _native_core_error or "schemasense-core package not installed."
        if os.getenv("SCHEMASENSE_DISABLE_NATIVE_CORE", "0").lower() in (
            "1",
            "true",
            "yes",
        ):
            reason = "Native acceleration disabled via SCHEMASENSE_DISABLE_NATIVE_CORE."
        return {
            "accelerated": False,
            "version": None,
            "reason": reason,
        }
    try:
        import schemasense_core  # type: ignore[import-untyped]

        return {
            "accelerated": True,
            "version": schemasense_core.version(),
            "build_info": dict(schemasense_core.build_info()),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "accelerated": False,
            "version": None,
            "reason": f"Failed to retrieve native build info: {exc}",
        }


__all__ = [
    "AIAgentError",
    "AIProviderError",
    "AIQuotaExceededError",
    "AISchemaHallucinationError",
    "AITimeoutError",
    "HAS_NATIVE_CORE",
    "SQLAgentResponse",
    "SchemaSenseAIAgent",
    "auth",
    "create_agent",
    "extract_sql_from_text",
    "get_native_core_info",
    "get_session_agent",
    "is_native_core_available",
    "verify_schema_fidelity",
]
