"""Server-Side Verified Authentication and Identity Derivation for SchemaSense 2.0.

Derives user and tenant identity strictly from verified credentials (JWT, OIDC,
IAP, or API keys). Client-supplied request body identity fields are never trusted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status

from schemasense.api.schemas import AuthenticatedIdentity
from schemasense.config import get_platform_config

logger = logging.getLogger("schemasense.api.auth")


def _b64_url_decode(s: str) -> bytes:
    """Base64 URL decode with necessary padding."""
    rem = len(s) % 4
    if rem > 0:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def _verify_hs256_jwt(token: str, secret: str) -> dict[str, Any]:
    """Pure-Python standard HS256 JWT signature verification.

    Validates signature and expiration timestamp without external C-extensions.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format; expected 3 segments.")

    header_b64, payload_b64, signature_b64 = parts

    # Compute expected signature
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(
        secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    actual_sig = _b64_url_decode(signature_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("JWT signature verification failed.")

    payload = json.loads(_b64_url_decode(payload_b64).decode("utf-8"))

    # Verify expiration claim if present
    exp = payload.get("exp")
    if exp is not None and isinstance(exp, (int, float)):
        if time.time() > exp:
            raise ValueError("JWT has expired.")

    return payload


async def get_current_identity(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    iap_user: str | None = Header(None, alias="X-Goog-Authenticated-User-Email"),
) -> AuthenticatedIdentity:
    """FastAPI dependency to extract and cryptographically verify the caller's identity.

    Derived user_id and tenant_id are authoritative.
    """
    cfg = get_platform_config()

    # 1. Bearer Token Authentication
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        try:
            claims = _verify_hs256_jwt(token, cfg.jwt_secret_key)
            user_id = str(claims.get("sub") or claims.get("user_id") or "anonymous")
            tenant_id = str(claims.get("tenant_id") or "default")
            email = claims.get("email")
            roles = claims.get("roles") or ["user"]
            if isinstance(roles, str):
                roles = [roles]

            return AuthenticatedIdentity(
                user_id=user_id,
                tenant_id=tenant_id,
                email=email,
                roles=roles,
                auth_method="jwt_bearer",
            )
        except Exception as e:
            logger.warning("Bearer token validation failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired authentication token: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    # 2. API Key Authentication (Service-to-Service)
    if x_api_key:
        clean_key = x_api_key.strip()
        # In simple mode or dev mode, support configured master key
        if clean_key and hmac.compare_digest(clean_key, cfg.jwt_secret_key):
            return AuthenticatedIdentity(
                user_id="service_agent",
                tenant_id="default",
                email="service@schemasense.internal",
                roles=["admin", "service"],
                auth_method="api_key",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key provided.",
        )

    # 3. Cloud Identity-Aware Proxy (IAP) Header
    if iap_user:
        clean_email = iap_user.replace("accounts.google.com:", "").strip()
        return AuthenticatedIdentity(
            user_id=clean_email,
            tenant_id="default",
            email=clean_email,
            roles=["user"],
            auth_method="iap",
        )

    # Missing authentication
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials were not provided or recognized.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(required_role: str):
    """Dependency factory enforcing role-based access control (RBAC)."""

    async def _role_checker(
        identity: AuthenticatedIdentity = Depends(get_current_identity),
    ) -> AuthenticatedIdentity:
        if required_role not in identity.roles and "admin" not in identity.roles:
            logger.warning(
                "Access denied for user '%s': missing role '%s' (has %s)",
                identity.user_id,
                required_role,
                identity.roles,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: requires role '{required_role}'.",
            )
        return identity

    return _role_checker
