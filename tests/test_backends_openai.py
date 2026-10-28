"""Unit tests for SchemaSense OpenAICompatBackend adapter."""

import json
import threading
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import BaseModel, Field

from schemasense.runtime.backends.base import (
    BackendCancelledError,
    BackendCapability,
    BackendNotAvailableError,
    BackendResourceError,
    BackendStructuredOutputError,
    BackendTimeoutError,
    GenerationRequest,
)
from schemasense.runtime.backends.openai_compat import (
    OpenAICompatBackend,
    is_placeholder_key,
)


class SampleModel(BaseModel):
    summary: str = Field(description="Summary text")
    confidence: float = Field(default=0.9)


def test_placeholder_key_detection():
    assert is_placeholder_key(None) is True
    assert is_placeholder_key("") is True
    assert is_placeholder_key("   ") is True
    assert is_placeholder_key("DEMO_KEY_STANDBY") is True
    assert is_placeholder_key("YOUR_API_KEY") is True
    assert is_placeholder_key("sk-validkey123456789") is False


def test_openai_backend_info_and_availability():
    backend = OpenAICompatBackend(
        model_name="gpt-4o",
        api_key="sk-test-key-12345",
        provider_name="openai",
    )
    info = backend.get_info()
    assert info.backend_id == "openai-gpt-4o"
    assert info.is_local is False
    assert BackendCapability.STREAMING in info.capabilities
    assert BackendCapability.STRUCTURED_OUTPUT in info.capabilities
    assert backend.is_available() is True


def test_azure_and_bedrock_and_cloudflare_backend_initialization():
    azure = OpenAICompatBackend(
        model_name="gpt-4o",
        api_key="azure-test-key",
        base_url="https://mycorp.openai.azure.com/openai/deployments/gpt-4o",
        provider_name="azure_openai",
    )
    headers = azure._build_headers()
    assert headers["api-key"] == "azure-test-key"
    assert "https://mycorp.openai.azure.com" in azure._get_completions_url()

    bedrock = OpenAICompatBackend(
        model_name="anthropic.claude-3-5-sonnet-20241022-v2:0",
        api_key="test-bedrock-token",
        base_url="http://localhost:8000/v1",
        provider_name="aws_bedrock",
    )
    assert bedrock.is_available() is True
    assert bedrock.get_info().backend_id.startswith("aws_bedrock")

    cf = OpenAICompatBackend(
        model_name="@cf/meta/llama-3.3-70b-instruct",
        api_key="cf-test-token",
        base_url="https://api.cloudflare.com/client/v4/accounts/12345/ai/v1",
        provider_name="cloudflare_workers_ai",
    )
    assert cf.is_available() is True
    assert cf.get_info().backend_id.startswith("cloudflare_workers_ai")


def test_ollama_local_declaration():
    backend = OpenAICompatBackend(
        model_name="llama3.2",
        provider_name="ollama",
        base_url="http://localhost:11434/v1",
    )
    info = backend.get_info()
    assert info.is_local is True
    assert backend.is_available() is True


def test_unavailable_when_missing_key():
    backend = OpenAICompatBackend(
        model_name="gpt-4o",
        api_key=None,
        provider_name="openai",
    )
    # With no key and no env var, it should not be available
    with patch(
        "schemasense.runtime.backends.openai_compat.load_openai_key", return_value=None
    ):
        backend.api_key = None
        assert backend.is_available() is False
        with pytest.raises(BackendNotAvailableError):
            backend.generate(GenerationRequest(prompt="Hello"))


@patch("httpx.Client")
def test_openai_generate_success(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {"content": "SELECT * FROM customers;"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8},
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = OpenAICompatBackend(
        model_name="gpt-4o-mini",
        api_key="sk-test-real-123",
        provider_name="openai",
    )

    req = GenerationRequest(prompt="List customers", temperature=0.2)
    res = backend.generate(req)

    assert res.text == "SELECT * FROM customers;"
    assert res.finish_reason == "stop"
    assert res.model_id == "gpt-4o-mini"
    assert res.tokens_prompt == 10
    assert res.tokens_completion == 8


@patch("httpx.Client")
def test_openai_structured_output_success(mock_client_cls):
    sample_json = json.dumps({"summary": "Customer summary", "confidence": 0.95})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {"content": f"```json\n{sample_json}\n```"},
                "finish_reason": "stop",
            }
        ]
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = OpenAICompatBackend(
        model_name="gpt-4o",
        api_key="sk-test-real-123",
    )

    req = GenerationRequest(prompt="Analyze", structured_schema=SampleModel)
    res = backend.generate(req)

    assert res.text is not None
    parsed = SampleModel.model_validate_json(
        res.text.strip().removeprefix("```json").removesuffix("```").strip()
    )
    assert parsed.summary == "Customer summary"
    assert parsed.confidence == 0.95


@patch("httpx.Client")
def test_openai_structured_output_error(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Not valid JSON"}, "finish_reason": "stop"}]
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = OpenAICompatBackend(model_name="gpt-4o", api_key="sk-test-real-123")
    req = GenerationRequest(prompt="Analyze", structured_schema=SampleModel)

    with pytest.raises(BackendStructuredOutputError):
        backend.generate(req)


@patch("httpx.Client")
def test_openai_rate_limit_and_auth_errors(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = OpenAICompatBackend(model_name="gpt-4o", api_key="sk-test-real-123")
    req = GenerationRequest(prompt="Analyze")

    # 401 Auth error
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_client.post.return_value = mock_resp_401
    with pytest.raises(BackendNotAvailableError):
        backend.generate(req)

    # 429 Rate limit
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_client.post.return_value = mock_resp_429
    with pytest.raises(BackendResourceError):
        backend.generate(req)


@patch("httpx.Client")
def test_openai_timeout_error(mock_client_cls):
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.TimeoutException("Read timeout")
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = OpenAICompatBackend(
        model_name="gpt-4o", api_key="sk-test-real-123", timeout_seconds=1.0
    )
    req = GenerationRequest(prompt="Analyze")

    with pytest.raises(BackendTimeoutError):
        backend.generate(req)


def test_openai_cancellation():
    backend = OpenAICompatBackend(model_name="gpt-4o", api_key="sk-test-real-123")
    cancel_token = threading.Event()
    cancel_token.set()

    with pytest.raises(BackendCancelledError):
        backend.generate(GenerationRequest(prompt="Analyze"), cancel_token=cancel_token)
