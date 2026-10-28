"""SchemaSense OpenAI-Compatible Inference Backend.

Universal adapter supporting OpenAI, DeepSeek, Groq, Mistral, Together, OpenRouter,
Ollama, vLLM, and any custom HTTP endpoint adhering to the OpenAI Chat Completions API.

Guarantees:
* Standardized request/response flow via httpx (no heavy vendor SDK dependencies).
* Structured output enforcement via json_schema / json_object or schema-grounded fallback.
* Streaming token generation with cancellation and timeout bounds.
* Zero secret leakage in logs or exceptions.
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

logger = logging.getLogger("schemasense.runtime.backends.openai_compat")

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

# Provider base URL presets
PROVIDER_PRESETS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1",
    "ollama": "http://localhost:11434/v1",
    "azure": "https://{resource}.openai.azure.com/openai/deployments/{deployment}",
    "azure_openai": "https://{resource}.openai.azure.com/openai/deployments/{deployment}",
    "bedrock": "http://localhost:8000/v1",
    "aws_bedrock": "http://localhost:8000/v1",
    "cloudflare": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
    "cloudflare_workers_ai": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
}

KNOWN_PLACEHOLDER_KEYS = frozenset(
    {
        "DEMO_KEY_STANDBY",
        "NO_KEY",
        "CHANGE_ME",
        "YOUR_API_KEY",
        "YOUR_OPENAI_API_KEY",
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


def load_openai_key(provider: str = "openai") -> str | None:
    """Loads API key from environment variables or Streamlit secrets."""
    normalized_provider = provider.upper().replace("-", "_").replace(" ", "_")
    env_vars = [
        f"{normalized_provider}_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AWS_BEDROCK_API_KEY",
        "CLOUDFLARE_API_TOKEN",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "OPENAI_API_KEY",
        "AI_GATEWAY_KEY",
        "CUSTOM_API_KEY",
    ]
    for var in env_vars:
        val = os.getenv(var, "").strip()
        if val and not is_placeholder_key(val):
            return val

    try:
        import streamlit as st

        for var in env_vars:
            val = st.secrets.get(var, "")
            if (
                val
                and isinstance(val, str)
                and val.strip()
                and not is_placeholder_key(val)
            ):
                return val.strip()
    except Exception:  # noqa: BLE001
        pass

    return None


class OpenAICompatBackend(InferenceBackend):
    """Universal OpenAI-compatible API inference adapter."""

    def __init__(
        self,
        model_name: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        provider_name: str = "openai",
        timeout_seconds: float = 30.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.provider_name = provider_name.lower().strip()
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.extra_headers = extra_headers or {}

        # Resolve base URL
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = PROVIDER_PRESETS.get(
                self.provider_name, DEFAULT_OPENAI_BASE_URL
            )

        # Resolve API key (Ollama allows empty keys)
        self.api_key = (
            api_key
            if api_key and not is_placeholder_key(api_key)
            else load_openai_key(self.provider_name)
        )
        if self.provider_name == "ollama" and not self.api_key:
            self.api_key = "ollama"

        # Capabilities
        caps = {
            BackendCapability.STREAMING,
            BackendCapability.STRUCTURED_OUTPUT,
            BackendCapability.CANCELLATION,
        }
        is_local = bool(
            self.provider_name == "ollama"
            or "localhost" in self.base_url
            or "127.0.0.1" in self.base_url
        )

        self._info = BackendInfo(
            backend_id=f"{self.provider_name}-{self.model_name}",
            display_name=f"{self.provider_name.title()} ({self.model_name})",
            is_local=is_local,
            capabilities=frozenset(caps),
            model_id=self.model_name,
            engine_version="openai-compat/1.0",
            requires_api_key=(self.provider_name != "ollama"),
        )

    def get_info(self) -> BackendInfo:
        return self._info

    def is_available(self) -> bool:
        if self.provider_name != "ollama" and (
            not self.api_key or is_placeholder_key(self.api_key)
        ):
            return False
        return True

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SchemaSense-Data-Steward/2.0",
        }
        if self.api_key and not is_placeholder_key(self.api_key):
            headers["Authorization"] = f"Bearer {self.api_key}"
            if "azure" in self.provider_name or "azure.com" in self.base_url:
                headers["api-key"] = self.api_key
        headers.update(self.extra_headers)
        return headers

    def _get_completions_url(self) -> str:
        """Computes the target completions endpoint, normalizing Azure or pre-formed URLs."""
        if "chat/completions" in self.base_url:
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _build_payload(
        self, request: GenerationRequest, stream: bool = False
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": request.temperature,
            "stream": stream,
        }

        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        # Structured output schema formatting
        if request.structured_schema:
            schema = request.structured_schema
            if hasattr(schema, "model_json_schema"):
                json_schema = schema.model_json_schema()
                schema_name = getattr(schema, "__name__", "StructuredOutput")
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": json_schema,
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}

        return payload

    def generate(
        self,
        request: GenerationRequest,
        cancel_token: threading.Event | None = None,
    ) -> GenerationResult:
        if not self.is_available():
            raise BackendNotAvailableError(
                f"{self.provider_name.title()} backend is not available (check API key configuration)."
            )

        if cancel_token and cancel_token.is_set():
            raise BackendCancelledError(
                "Generation cancelled prior to request execution."
            )

        timeout = request.timeout_seconds or self.timeout_seconds
        url = self._get_completions_url()
        headers = self._build_headers()
        payload = self._build_payload(request, stream=False)

        start_time = time.monotonic()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, json=payload)

            elapsed = time.monotonic() - start_time
            if response.status_code == 401:
                raise BackendNotAvailableError(
                    f"{self.provider_name.title()} authentication failed: invalid API key."
                )
            if response.status_code == 429:
                raise BackendResourceError(
                    f"{self.provider_name.title()} rate limit / quota exceeded (HTTP 429)."
                )
            if response.status_code >= 400:
                raise InferenceBackendError(
                    f"{self.provider_name.title()} API error {response.status_code}: {response.text[:300]}"
                )

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                raise InferenceBackendError(
                    "Empty choices returned from completions endpoint."
                )

            message = choices[0].get("message", {})
            text = message.get("content", "") or ""
            finish_reason = choices[0].get("finish_reason", "stop")

            # Structured output validation
            if request.structured_schema:
                try:
                    clean_text = text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    parsed_dict = json.loads(clean_text)
                    if hasattr(request.structured_schema, "model_validate"):
                        request.structured_schema.model_validate(parsed_dict)
                except Exception as exc:
                    raise BackendStructuredOutputError(
                        f"Failed to parse structured output conforming to schema: {exc}"
                    ) from exc

            usage = data.get("usage", {})
            return GenerationResult(
                text=text,
                model_id=self.model_name,
                backend_id=self._info.backend_id,
                finish_reason=finish_reason,
                tokens_prompt=usage.get("prompt_tokens"),
                tokens_completion=usage.get("completion_tokens"),
                elapsed_ms=round(elapsed * 1000, 2),
            )

        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(
                f"{self.provider_name.title()} request timed out after {timeout:.1f}s."
            ) from exc
        except (
            BackendNotAvailableError,
            BackendResourceError,
            BackendStructuredOutputError,
            BackendTimeoutError,
        ):
            raise
        except Exception as exc:
            raise InferenceBackendError(
                f"{self.provider_name.title()} generation failed: {exc}"
            ) from exc

    def generate_stream(
        self,
        request: GenerationRequest,
        cancel_token: threading.Event | None = None,
    ) -> Iterator[str]:
        if not self.is_available():
            raise BackendNotAvailableError(
                f"{self.provider_name.title()} backend is not available (check API key configuration)."
            )

        timeout = request.timeout_seconds or self.timeout_seconds
        url = self._get_completions_url()
        headers = self._build_headers()
        payload = self._build_payload(request, stream=True)

        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    if response.status_code == 401:
                        raise BackendNotAvailableError(
                            f"{self.provider_name.title()} authentication failed."
                        )
                    if response.status_code == 429:
                        raise BackendResourceError(
                            f"{self.provider_name.title()} rate limit exceeded (HTTP 429)."
                        )
                    if response.status_code >= 400:
                        raise InferenceBackendError(
                            f"{self.provider_name.title()} streaming error {response.status_code}"
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
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(
                f"Streaming timed out after {timeout:.1f}s."
            ) from exc
        except (
            BackendNotAvailableError,
            BackendResourceError,
            BackendCancelledError,
            BackendTimeoutError,
        ):
            raise
        except Exception as exc:
            raise InferenceBackendError(f"Streaming failed: {exc}") from exc
