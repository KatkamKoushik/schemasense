"""
Enterprise Authentication and OAuth 2.0 Gateway for SchemaSense AI.
Supports Google OAuth 2.0, GitHub OAuth 2.0, Streamlit Native OIDC,
Identity-Aware Proxy (IAP) headers, and Enterprise Access Token gating.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("schemasense.auth")


class OAuthStateError(ValueError):
    """Raised when an OAuth 2.0 callback state parameter is invalid, expired, missing, or mismatched."""


def generate_oauth_state(provider: str) -> str:
    """Generates an unguessable 32-byte cryptographic state nonce bound to the authentication provider."""
    clean_provider = provider.strip().lower()
    return f"{clean_provider}_{secrets.token_urlsafe(32)}"


def verify_oauth_state(
    received_state: Optional[str], expected_state: Optional[str]
) -> bool:
    """
    Constant-time comparison validating that the callback state matches the browser's session nonce.
    Prevents OAuth login CSRF and cross-session authentication hijacking.
    """
    if not received_state or not expected_state:
        return False
    return secrets.compare_digest(
        str(received_state).strip(), str(expected_state).strip()
    )


# OAuth 2.0 Provider Endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USERINFO_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def get_secret(key_path: list[str], default: Any = None) -> Any:
    """Safely retrieves a nested key from st.secrets without raising exceptions."""
    try:
        import streamlit as st

        val = st.secrets
        for k in key_path:
            if not isinstance(val, (dict, object)) or k not in val:
                return default
            val = val[k]
        return val
    except Exception:  # noqa: BLE001
        return default


def resolve_redirect_uri(explicit_uri: Optional[str] = None) -> str:
    """
    Resolves the OAuth callback redirect URI based on:
    1. Explicit override argument
    2. SCHEMASENSE_REDIRECT_URI environment variable
    3. Incoming Streamlit request headers (host, x-forwarded-host, x-forwarded-proto)
    4. Configured secrets.toml redirect_uri
    5. Default localhost development URI (http://localhost:8501)
    """
    if explicit_uri:
        return explicit_uri

    if env_uri := os.getenv("SCHEMASENSE_REDIRECT_URI"):
        return env_uri

    try:
        import streamlit as st

        if hasattr(st, "context") and hasattr(st.context, "headers"):
            headers: dict[str, Any] = dict(st.context.headers or {})
            host = headers.get("x-forwarded-host") or headers.get("host")
            if host:
                proto = headers.get("x-forwarded-proto")
                if not proto:
                    proto = "https" if ".streamlit.app" in host else "http"
                return f"{proto}://{host}".rstrip("/")
    except Exception:  # noqa: BLE001
        pass

    secret_uri = get_secret(["auth", "redirect_uri"])
    if secret_uri and "oauth2callback" not in secret_uri:
        return secret_uri

    return "http://localhost:8501"


def get_google_config(redirect_uri: Optional[str] = None) -> Optional[dict[str, str]]:
    """Retrieves Google OAuth client configuration from env or secrets."""
    client_id = (
        os.getenv("GOOGLE_CLIENT_ID")
        or get_secret(["auth", "google", "client_id"])
        or get_secret(["auth", "client_id"])
    )
    client_secret = (
        os.getenv("GOOGLE_CLIENT_SECRET")
        or get_secret(["auth", "google", "client_secret"])
        or get_secret(["auth", "client_secret"])
    )
    if not client_id or not client_secret:
        return None

    configured_uri = (
        redirect_uri
        or get_secret(["auth", "google", "redirect_uri"])
        or resolve_redirect_uri()
    )
    return {
        "client_id": str(client_id).strip(),
        "client_secret": str(client_secret).strip(),
        "redirect_uri": configured_uri,
    }


def get_github_config(redirect_uri: Optional[str] = None) -> Optional[dict[str, str]]:
    """Retrieves GitHub OAuth client configuration from env or secrets."""
    client_id = os.getenv("GITHUB_CLIENT_ID") or get_secret(
        ["auth", "github", "client_id"]
    )
    client_secret = os.getenv("GITHUB_CLIENT_SECRET") or get_secret(
        ["auth", "github", "client_secret"]
    )
    if not client_id or not client_secret:
        return None

    configured_uri = (
        redirect_uri
        or get_secret(["auth", "github", "redirect_uri"])
        or resolve_redirect_uri()
    )
    return {
        "client_id": str(client_id).strip(),
        "client_secret": str(client_secret).strip(),
        "redirect_uri": configured_uri,
    }


def is_oauth_configured() -> bool:
    """Checks whether either Google or GitHub OAuth is configured."""
    return get_google_config() is not None or get_github_config() is not None


def get_google_auth_url(
    redirect_uri: Optional[str] = None, state: Optional[str] = None
) -> Optional[str]:
    """Generates the Google OAuth 2.0 authorization URL."""
    cfg = get_google_config(redirect_uri)
    if not cfg:
        return None

    state_token = state or generate_oauth_state("google")
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state_token,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def get_github_auth_url(
    redirect_uri: Optional[str] = None, state: Optional[str] = None
) -> Optional[str]:
    """Generates the GitHub OAuth 2.0 authorization URL."""
    cfg = get_github_config(redirect_uri)
    if not cfg:
        return None

    state_token = state or generate_oauth_state("github")
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "scope": "read:user user:email",
        "state": state_token,
    }
    return f"{GITHUB_AUTH_URL}?{urlencode(params)}"


def exchange_google_code(
    code: str, redirect_uri: Optional[str] = None
) -> dict[str, Any]:
    """Exchanges a Google authorization code for access tokens and user profile."""
    cfg = get_google_config(redirect_uri)
    if not cfg:
        raise ValueError("Google OAuth credentials are not configured.")

    token_data = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": cfg["redirect_uri"],
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(GOOGLE_TOKEN_URL, data=token_data)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Google token exchange failed ({resp.status_code}): {resp.text}"
            )
        tokens = resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise RuntimeError(
                "Google token exchange response did not contain an access_token."
            )

        user_resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch Google userinfo ({user_resp.status_code}): {user_resp.text}"
            )
        user_info = user_resp.json()

    return {
        "provider": "Google",
        "user_id": user_info.get("id"),
        "email": user_info.get("email"),
        "name": user_info.get("name") or user_info.get("email", "Google User"),
        "avatar_url": user_info.get("picture"),
        "auth_method": "Google OAuth 2.0",
    }


def exchange_github_code(
    code: str, redirect_uri: Optional[str] = None
) -> dict[str, Any]:
    """Exchanges a GitHub authorization code for access tokens and user profile."""
    cfg = get_github_config(redirect_uri)
    if not cfg:
        raise ValueError("GitHub OAuth credentials are not configured.")

    token_data = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
    }
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            GITHUB_TOKEN_URL,
            data=token_data,
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"GitHub token exchange failed ({resp.status_code}): {resp.text}"
            )
        tokens = resp.json()
        if "error" in tokens:
            raise RuntimeError(
                f"GitHub OAuth error: {tokens.get('error_description') or tokens.get('error')}"
            )
        access_token = tokens.get("access_token")
        if not access_token:
            raise RuntimeError(
                "GitHub token exchange response did not contain an access_token."
            )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "SchemaSense-Enterprise-Console",
        }
        user_resp = client.get(GITHUB_USERINFO_URL, headers=headers)
        if user_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch GitHub profile ({user_resp.status_code}): {user_resp.text}"
            )
        user_info = user_resp.json()

        email = user_info.get("email")
        if not email:
            emails_resp = client.get(GITHUB_EMAILS_URL, headers=headers)
            if emails_resp.status_code == 200:
                emails = emails_resp.json()
                for item in emails:
                    if item.get("primary") and item.get("verified"):
                        email = item.get("email")
                        break
                if not email and emails:
                    email = emails[0].get("email")

    return {
        "provider": "GitHub",
        "user_id": str(user_info.get("id")),
        "login": user_info.get("login"),
        "email": email or f"{user_info.get('login')}@users.noreply.github.com",
        "name": user_info.get("name") or user_info.get("login", "GitHub User"),
        "avatar_url": user_info.get("avatar_url"),
        "auth_method": "GitHub OAuth 2.0",
    }


def exchange_oauth_code(
    code: str,
    state: Optional[str] = None,
    expected_state: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> dict[str, Any]:
    """Exchanges an authorization code with the provider identified by state or configuration."""
    if expected_state is not None:
        if not verify_oauth_state(state, expected_state):
            raise OAuthStateError(
                "OAuth state validation failed: state token mismatch, expired, or CSRF detected."
            )

    state_str = str(state or "")
    if state_str.startswith("google_") or state_str == "google":
        return exchange_google_code(code, redirect_uri)
    elif state_str.startswith("github_") or state_str == "github":
        return exchange_github_code(code, redirect_uri)

    # Disambiguate if state was generic or absent
    if get_google_config():
        try:
            return exchange_google_code(code, redirect_uri)
        except Exception:
            if get_github_config():
                return exchange_github_code(code, redirect_uri)
            raise
    elif get_github_config():
        return exchange_github_code(code, redirect_uri)

    raise ValueError("Neither Google nor GitHub OAuth credentials are configured.")


def is_production_environment(
    schemasense_env: Optional[str] = None,
    environment: Optional[str] = None,
) -> bool:
    """Checks whether the environment indicates production.

    Fail-closed invariant: If either SCHEMASENSE_ENV or ENVIRONMENT indicates
    production (case-insensitive 'production' or 'prod'), the environment is
    strictly treated as production. Conflicting values (e.g. one development,
    one production) resolve safely to production.
    """
    if schemasense_env is None:
        schemasense_env = os.getenv("SCHEMASENSE_ENV", "")
        if not schemasense_env:
            schemasense_env = str(get_secret(["general", "environment"], "") or "")

    if environment is None:
        environment = os.getenv("ENVIRONMENT", "")

    s_env = (schemasense_env or "").strip().lower()
    e_env = (environment or "").strip().lower()

    prod_tokens = {"production", "prod"}
    return s_env in prod_tokens or e_env in prod_tokens


def is_local_evaluation_permitted(
    *,
    enable_eval: Optional[Any] = None,
    schemasense_env: Optional[str] = None,
    environment: Optional[str] = None,
    access_key: Optional[str] = None,
    require_auth: Optional[Any] = None,
) -> bool:
    """Determines whether the local-operator evaluation mode bypass is permitted.

    Required security safeguards:
    1. Production guard: Production environments must NEVER permit the local
       evaluation bypass, regardless of opt-in configuration.
    2. Authentication requirement guard: A configured SCHEMASENSE_ACCESS_KEY,
       SCHEMASENSE_AUTH_KEY, or SCHEMASENSE_REQUIRE_AUTH must not be bypassed.
    3. Explicit opt-in: Local evaluation must be explicitly enabled via
       SCHEMASENSE_ENABLE_LOCAL_EVALUATION ('true', '1', 'yes'). Defaults to False.
    4. Fail-closed: Missing, invalid, or ambiguous configurations evaluate to False.
    """
    # 1. Production must never permit the evaluation bypass
    if is_production_environment(
        schemasense_env=schemasense_env, environment=environment
    ):
        return False

    # 2. Configured access key or mandatory auth must not be bypassed
    if access_key is None:
        access_key = os.getenv("SCHEMASENSE_ACCESS_KEY") or os.getenv(
            "SCHEMASENSE_AUTH_KEY"
        )
        if not access_key:
            access_key = str(get_secret(["auth", "access_token"], "") or "")
    if (access_key or "").strip():
        return False

    if require_auth is None:
        require_auth = os.getenv("SCHEMASENSE_REQUIRE_AUTH", "")
        if not require_auth:
            require_auth = get_secret(["auth", "require_auth"], False)
    if isinstance(require_auth, bool):
        if require_auth:
            return False
    elif str(require_auth).strip().lower() in ("true", "1", "yes"):
        return False

    # 3. Explicit opt-in check (fails closed on missing, invalid, or ambiguous values)
    if enable_eval is None:
        enable_eval = os.getenv("SCHEMASENSE_ENABLE_LOCAL_EVALUATION", "")
        if not enable_eval:
            enable_eval = get_secret(["auth", "enable_local_evaluation"], False)

    if isinstance(enable_eval, bool):
        return enable_eval

    clean_eval = str(enable_eval).strip().lower()
    return clean_eval in ("true", "1", "yes")
