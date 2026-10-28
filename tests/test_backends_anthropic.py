"""Unit tests for SchemaSense AnthropicBackend adapter."""

import threading
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import BaseModel, Field

from schemasense.runtime.backends.anthropic_backend import (
    AnthropicBackend,
    is_placeholder_key,
)
from schemasense.runtime.backends.base import (
    BackendCancelledError,
    BackendCapability,
    BackendNotAvailableError,
    BackendResourceError,
    BackendTimeoutError,
    GenerationRequest,
)


class SampleModel(BaseModel):
    sql: str = Field(description="Generated SQL query")
    reasoning: str = Field(description="Explanation")


def test_anthropic_placeholder_key_detection():
    assert is_placeholder_key(None) is True
    assert is_placeholder_key("") is True
    assert is_placeholder_key("DEMO_KEY_STANDBY") is True
    assert is_placeholder_key("YOUR_ANTHROPIC_API_KEY") is True
    assert is_placeholder_key("sk-ant-api03-validkey") is False


def test_anthropic_info_and_availability():
    backend = AnthropicBackend(
        model_name="claude-3-5-sonnet-20241022",
        api_key="sk-ant-test-key",
    )
    info = backend.get_info()
    assert info.backend_id == "anthropic-claude-3-5-sonnet-20241022"
    assert info.is_local is False
    assert BackendCapability.STREAMING in info.capabilities
    assert BackendCapability.STRUCTURED_OUTPUT in info.capabilities
    assert backend.is_available() is True


def test_anthropic_unavailable_without_key():
    with patch(
        "schemasense.runtime.backends.anthropic_backend.load_anthropic_key",
        return_value=None,
    ):
        backend = AnthropicBackend(api_key=None)
        assert backend.is_available() is False
        with pytest.raises(BackendNotAvailableError):
            backend.generate(GenerationRequest(prompt="Hello"))


@patch("httpx.Client")
def test_anthropic_generate_text_success(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": "SELECT COUNT(*) FROM orders;"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 15, "output_tokens": 10},
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = AnthropicBackend(
        model_name="claude-3-5-sonnet-20241022",
        api_key="sk-ant-test-key",
    )
    req = GenerationRequest(prompt="Count orders")
    res = backend.generate(req)

    assert res.text == "SELECT COUNT(*) FROM orders;"
    assert res.finish_reason == "end_turn"
    assert res.tokens_prompt == 15
    assert res.tokens_completion == 10


@patch("httpx.Client")
def test_anthropic_structured_tool_use_success(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [
            {
                "type": "tool_use",
                "name": "extract_schema_response",
                "input": {"sql": "SELECT id FROM users;", "reasoning": "Simple select"},
            }
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 20, "output_tokens": 15},
    }
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = AnthropicBackend(api_key="sk-ant-test-key")
    req = GenerationRequest(prompt="Fetch user IDs", structured_schema=SampleModel)
    res = backend.generate(req)

    assert res.text is not None
    parsed = SampleModel.model_validate_json(res.text)
    assert parsed.sql == "SELECT id FROM users;"
    assert parsed.reasoning == "Simple select"


@patch("httpx.Client")
def test_anthropic_errors_and_timeout(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client

    backend = AnthropicBackend(api_key="sk-ant-test-key")
    req = GenerationRequest(prompt="Analyze")

    # 401
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_client.post.return_value = mock_resp_401
    with pytest.raises(BackendNotAvailableError):
        backend.generate(req)

    # 429
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_client.post.return_value = mock_resp_429
    with pytest.raises(BackendResourceError):
        backend.generate(req)

    # Timeout
    mock_client.post.side_effect = httpx.TimeoutException("Anthropic timed out")
    with pytest.raises(BackendTimeoutError):
        backend.generate(req)


def test_anthropic_cancellation():
    backend = AnthropicBackend(api_key="sk-ant-test-key")
    cancel_token = threading.Event()
    cancel_token.set()

    with pytest.raises(BackendCancelledError):
        backend.generate(GenerationRequest(prompt="Analyze"), cancel_token=cancel_token)
