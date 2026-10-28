"""SchemaSense Anthropic Claude Inference Backend.

Adapter supporting Anthropic Claude models (Claude 3.5 Sonnet, Claude 3.5 Haiku, Claude 3 Opus)
via the native Messages API with tool_use schema extraction and streaming.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx

from schemasense.runtime.backends.base import (
    BackendCancelledError,
    BackendCapability,
    BackendInfo,
    BackendNotAvailableError,
    BackendResourceError,
    BackendStructuredOutputError,
    BackendTimeoutError,
    GenerationRequest,
    GenerationResult,
    InferenceBackend,
    InferenceBackendError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("schemasense.runtime.backends.anthropic")

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"

KNOWN_PLACEHOLDER_KEYS = frozenset(
    {
        "DEMO_KEY_STANDBY",
        "NO_KEY",
        "CHANGE_ME",
        "YOUR_API_KEY",
        "YOUR_ANTHROPIC_API_KEY",
        "PLACEHOLDER",
        "DUMMY",
        "DEMO",
    }
)


def is_placeholder_key(key: str | None) -> bool:
    """Return True if the key is empty, None, or a placeholder."""
    if not key or not isinstance(key, str):
        return True
    cleaned = key.strip()
    if not cleaned:
        return True
    upper = cleaned.upper()
    if upper in KNOWN_PLACEHOLDER_KEYS:
        return True
    return upper.startswith(("DEMO_KEY", "PLACEHOLDER_", "YOUR_"))


def load_anthropic_key() -> str | None:
    """Loads Anthropic API key from environment variables or Streamlit secrets."""
    val = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if val and not is_placeholder_key(val):
        return val

    try:
        import streamlit as st

        val = st.secrets.get("ANTHROPIC_API_KEY", "")
        if val and isinstance(val, str) and val.strip() and not is_placeholder_key(val):
            return val.strip()
    except Exception:  # noqa: BLE001
        pass

    return None


class AnthropicBackend(InferenceBackend):
    """Native Anthropic Messages API inference adapter."""

    def __init__(
        self,
        model_name: str = "claude-3-5-sonnet-20241022",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.base_url = (base_url or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
        self.api_key = (
            api_key
            if api_key and not is_placeholder_key(api_key)
            else load_anthropic_key()
        )

        caps = {
            BackendCapability.STREAMING,
            BackendCapability.STRUCTURED_OUTPUT,
            BackendCapability.CANCELLATION,
        }
        self._info = BackendInfo(
            backend_id=f"anthropic-{self.model_name}",
            display_name=f"Anthropic ({self.model_name})",
            is_local=False,
            capabilities=frozenset(caps),
            model_id=self.model_name,
            engine_version="anthropic/2023-06-01",
            requires_api_key=True,
        )

    def get_info(self) -> BackendInfo:
        return self._info

    def is_available(self) -> bool:
        return bool(self.api_key and not is_placeholder_key(self.api_key))

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "User-Agent": "SchemaSense-Data-Steward/2.0",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _build_payload(
        self, request: GenerationRequest, stream: bool = False
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": request.max_tokens or 4096,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.system_instruction:
            payload["system"] = request.system_instruction

        # Following llm-structured-output skill: tool_use schema extraction
        if request.structured_schema:
            schema = request.structured_schema
            if hasattr(schema, "model_json_schema"):
                json_schema = schema.model_json_schema()
            else:
                json_schema = {"type": "object"}

            payload["tools"] = [
                {
                    "name": "extract_schema_response",
                    "description": "Extract structured database schema analysis and verified SQL statement.",
                    "input_schema": json_schema,
                }
            ]
            payload["tool_choice"] = {"type": "tool", "name": "extract_schema_response"}

        return payload

    def generate(
        self,
        request: GenerationRequest,
        cancel_token: threading.Event | None = None,
    ) -> GenerationResult:
        if not self.is_available():
            raise BackendNotAvailableError(
                "Anthropic backend is not available (check ANTHROPIC_API_KEY)."
            )

        if cancel_token and cancel_token.is_set():
            raise BackendCancelledError(
                "Generation cancelled prior to request execution."
            )

        timeout = request.timeout_seconds or self.timeout_seconds
        url = f"{self.base_url}/messages"
        headers = self._build_headers()
        payload = self._build_payload(request, stream=False)

        start_time = time.monotonic()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)

            elapsed = time.monotonic() - start_time
            if response.status_code == 401:
                raise BackendNotAvailableError(
                    "Anthropic authentication failed: invalid API key."
                )
            if response.status_code == 429:
                raise BackendResourceError(
                    "Anthropic rate limit / credit balance exhausted (HTTP 429)."
                )
            if response.status_code >= 400:
                raise InferenceBackendError(
                    f"Anthropic API error {response.status_code}: {response.text[:300]}"
                )

            data = response.json()
            content_blocks = data.get("content", [])

            text_parts = []
            structured_data = None

            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif (
                    block.get("type") == "tool_use"
                    and block.get("name") == "extract_schema_response"
                ):
                    tool_input = block.get("input", {})
                    if request.structured_schema:
                        try:
                            if hasattr(request.structured_schema, "model_validate"):
                                structured_data = (
                                    request.structured_schema.model_validate(tool_input)
                                )
                            else:
                                structured_data = tool_input
                        except Exception as exc:
                            raise BackendStructuredOutputError(
                                f"Failed to validate tool_use output: {exc}"
                            ) from exc

            text = "".join(text_parts)
            if not text and structured_data:
                text = json.dumps(
                    structured_data
                    if isinstance(structured_data, dict)
                    else structured_data.model_dump()
                )

            usage = data.get("usage", {})
            return GenerationResult(
                text=text,
                model_id=self.model_name,
                backend_id=self._info.backend_id,
                finish_reason=data.get("stop_reason", "end_turn"),
                tokens_prompt=usage.get("input_tokens"),
                tokens_completion=usage.get("output_tokens"),
                elapsed_ms=round(elapsed * 1000, 2),
            )

        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(
                f"Anthropic request timed out after {timeout:.1f}s."
            ) from exc
        except (
            BackendNotAvailableError,
            BackendResourceError,
            BackendStructuredOutputError,
            BackendTimeoutError,
        ):
            raise
        except Exception as exc:
            raise InferenceBackendError(f"Anthropic generation failed: {exc}") from exc

    def generate_stream(
        self,
        request: GenerationRequest,
        cancel_token: threading.Event | None = None,
    ) -> Iterator[str]:
        if not self.is_available():
            raise BackendNotAvailableError(
                "Anthropic backend is not available (check ANTHROPIC_API_KEY)."
            )

        timeout = request.timeout_seconds or self.timeout_seconds
        url = f"{self.base_url}/messages"
        headers = self._build_headers()
        payload = self._build_payload(request, stream=True)

        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    if response.status_code == 401:
                        raise BackendNotAvailableError(
                            "Anthropic authentication failed."
                        )
                    if response.status_code == 429:
                        raise BackendResourceError(
                            "Anthropic rate limit exceeded (HTTP 429)."
                        )
                    if response.status_code >= 400:
                        raise InferenceBackendError(
                            f"Anthropic streaming error {response.status_code}"
                        )

                    for line in response.iter_lines():
                        if cancel_token and cancel_token.is_set():
                            raise BackendCancelledError(
                                "Streaming cancelled by client token."
                            )

                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue

                        data_str = line[5:].strip()
                        try:
                            event_data = json.loads(data_str)
                            event_type = event_data.get("type")
                            if event_type == "content_block_delta":
                                delta = event_data.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield delta.get("text", "")
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(
                f"Anthropic streaming timed out after {timeout:.1f}s."
            ) from exc
        except (
            BackendNotAvailableError,
            BackendResourceError,
            BackendCancelledError,
            BackendTimeoutError,
        ):
            raise
        except Exception as exc:
            raise InferenceBackendError(f"Anthropic streaming failed: {exc}") from exc
