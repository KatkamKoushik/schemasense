"""Unit tests for schemasense.auth OAuth 2.0 and enterprise identity gateway."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from schemasense.auth import (
    exchange_github_code,
    exchange_google_code,
    exchange_oauth_code,
    get_github_auth_url,
    get_github_config,
    get_google_auth_url,
    get_google_config,
    is_oauth_configured,
    resolve_redirect_uri,
)


def test_resolve_redirect_uri_default(monkeypatch):
    """Verifies fallback to localhost default when no headers or env are set."""
    monkeypatch.delenv("SCHEMASENSE_REDIRECT_URI", raising=False)
    uri = resolve_redirect_uri()
    assert uri == "http://localhost:8501"


def test_resolve_redirect_uri_explicit():
    """Verifies that an explicit override takes precedence."""
    uri = resolve_redirect_uri(
        explicit_uri="https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app"
    )
    assert (
        uri == "https://neural-nexus-schemasense-n9aixu78zu8ebbbahcvvhc.streamlit.app"
    )


def test_resolve_redirect_uri_env(monkeypatch):
    """Verifies that SCHEMASENSE_REDIRECT_URI environment variable is respected."""
    monkeypatch.setenv("SCHEMASENSE_REDIRECT_URI", "https://custom-console.example.com")
    uri = resolve_redirect_uri()
    assert uri == "https://custom-console.example.com"


def test_oauth_unconfigured_defaults(monkeypatch):
    """Verifies configs and URLs return None when no credentials are present."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)

    with patch("schemasense.auth.get_secret", return_value=None):
        assert get_google_config() is None
        assert get_github_config() is None
        assert is_oauth_configured() is False
        assert get_google_auth_url() is None
        assert get_github_auth_url() is None


def test_google_auth_url_generation(monkeypatch):
    """Verifies Google auth URL parameters and encoding."""
    monkeypatch.setenv(
        "GOOGLE_CLIENT_ID", "mock-google-client-id.apps.googleusercontent.com"
    )
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "mock-google-secret")

    with patch("schemasense.auth.get_secret", return_value=None):
        assert is_oauth_configured() is True
        cfg = get_google_config()
        assert cfg is not None
        assert cfg["client_id"] == "mock-google-client-id.apps.googleusercontent.com"

        url = get_google_auth_url(state="google_teststate123")
        assert url is not None
        assert "https://accounts.google.com/o/oauth2/v2/auth?" in url
        assert "client_id=mock-google-client-id.apps.googleusercontent.com" in url
        assert "response_type=code" in url
        assert "state=google_teststate123" in url


def test_github_auth_url_generation(monkeypatch):
    """Verifies GitHub auth URL parameters and encoding."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "mock-github-client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "mock-github-secret")

    with patch("schemasense.auth.get_secret", return_value=None):
        assert is_oauth_configured() is True
        cfg = get_github_config()
        assert cfg is not None
        assert cfg["client_id"] == "mock-github-client-id"

        url = get_github_auth_url(state="github_teststate456")
        assert url is not None
        assert "https://github.com/login/oauth/authorize?" in url
        assert "client_id=mock-github-client-id" in url
        assert "state=github_teststate456" in url


def test_exchange_google_code_success(monkeypatch):
    """Verifies successful token and userinfo exchange for Google."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "mock-google-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "mock-google-secret")

    token_mock = MagicMock()
    token_mock.status_code = 200
    token_mock.json.return_value = {"access_token": "ya29.mock_google_token"}

    user_mock = MagicMock()
    user_mock.status_code = 200
    user_mock.json.return_value = {
        "id": "10987654321",
        "email": "analyst@enterprise.com",
        "name": "Jane Analyst",
        "picture": "https://lh3.googleusercontent.com/photo.jpg",
    }

    with (
        patch("httpx.Client.post", return_value=token_mock),
        patch("httpx.Client.get", return_value=user_mock),
    ):
        result = exchange_google_code(code="mock_auth_code")
        assert result["provider"] == "Google"
        assert result["email"] == "analyst@enterprise.com"
        assert result["name"] == "Jane Analyst"
        assert result["auth_method"] == "Google OAuth 2.0"
        assert result["avatar_url"] == "https://lh3.googleusercontent.com/photo.jpg"


def test_exchange_github_code_success(monkeypatch):
    """Verifies successful token and userinfo exchange for GitHub."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "mock-gh-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "mock-gh-secret")

    token_mock = MagicMock()
    token_mock.status_code = 200
    token_mock.json.return_value = {"access_token": "gho_mock_token"}

    user_mock = MagicMock()
    user_mock.status_code = 200
    user_mock.json.return_value = {
        "id": 1234567,
        "login": "koushik-dev",
        "name": "Koushik Katkam",
        "email": "koushik@example.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/1234567",
    }

    with (
        patch("httpx.Client.post", return_value=token_mock),
        patch("httpx.Client.get", return_value=user_mock),
    ):
        result = exchange_github_code(code="mock_gh_code")
        assert result["provider"] == "GitHub"
        assert result["login"] == "koushik-dev"
        assert result["name"] == "Koushik Katkam"
        assert result["email"] == "koushik@example.com"
        assert result["auth_method"] == "GitHub OAuth 2.0"


def test_exchange_oauth_code_routing(monkeypatch):
    """Verifies dispatcher routes according to state prefix."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "mock-google-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "mock-google-secret")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "mock-gh-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "mock-gh-secret")

    with (
        patch(
            "schemasense.auth.exchange_google_code",
            return_value={"provider": "Google", "name": "Google User"},
        ) as mock_g,
        patch(
            "schemasense.auth.exchange_github_code",
            return_value={"provider": "GitHub", "name": "GitHub User"},
        ) as mock_gh,
    ):
        r1 = exchange_oauth_code(code="c1", state="google_abc")
        assert r1["provider"] == "Google"
        mock_g.assert_called_once()

        r2 = exchange_oauth_code(code="c2", state="github_xyz")
        assert r2["provider"] == "GitHub"
        mock_gh.assert_called_once()


def test_exchange_google_code_failure(monkeypatch):
    """Verifies exception handling when provider rejects authorization code."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "mock-google-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "mock-google-secret")

    err_mock = MagicMock()
    err_mock.status_code = 400
    err_mock.text = "invalid_grant"

    with patch("httpx.Client.post", return_value=err_mock):
        with pytest.raises(RuntimeError, match="Google token exchange failed"):
            exchange_google_code(code="bad_code")
