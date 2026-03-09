from typing import Any

from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token

from second_brain_service.common.config import (
    PUBLIC_BASE_URL,
    REMOTE_ALLOWED_DOMAINS,
    REMOTE_ALLOWED_EMAILS,
    REMOTE_MCP_AUTH_REQUIRED,
    REMOTE_MCP_GOOGLE_CLIENT_ID,
    REMOTE_MCP_GOOGLE_CLIENT_SECRET,
)


def build_google_auth_provider() -> GoogleProvider:
    if not REMOTE_MCP_AUTH_REQUIRED:
        raise RuntimeError("remote MCP auth is disabled; refusing to build an auth provider")
    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL must be set for remote MCP auth")
    if not REMOTE_MCP_GOOGLE_CLIENT_ID or not REMOTE_MCP_GOOGLE_CLIENT_SECRET:
        raise RuntimeError("REMOTE_MCP_GOOGLE_CLIENT_ID and REMOTE_MCP_GOOGLE_CLIENT_SECRET must be set")

    return GoogleProvider(
        client_id=REMOTE_MCP_GOOGLE_CLIENT_ID,
        client_secret=REMOTE_MCP_GOOGLE_CLIENT_SECRET,
        base_url=PUBLIC_BASE_URL,
        required_scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
    )


def _is_allowed_email(email: str) -> bool:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return False
    if normalized in REMOTE_ALLOWED_EMAILS:
        return True
    domain = normalized.split("@", 1)[1]
    return domain in REMOTE_ALLOWED_DOMAINS


def require_allowed_user() -> dict[str, Any]:
    if not REMOTE_MCP_AUTH_REQUIRED:
        return {"auth": "disabled"}

    token = get_access_token()
    if token is None:
        raise PermissionError("missing access token")

    claims = token.claims or {}
    email = str(claims.get("email", "")).strip().lower()
    email_verified = claims.get("email_verified")

    if email_verified is False:
        raise PermissionError("email is not verified")

    if not REMOTE_ALLOWED_EMAILS and not REMOTE_ALLOWED_DOMAINS:
        raise PermissionError("no allowlist configured for remote MCP access")

    if not _is_allowed_email(email):
        raise PermissionError(f"account not allowed: {email or 'unknown'}")

    return claims
