"""X OAuth 2.0 Authorization Code + PKCE (official recommended user-context flow)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.config import get_settings

AUTH_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
ME_URL = "https://api.x.com/2/users/me"


class XOAuthNotConfigured(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "X OAuth is not configured. Create an X Developer App at "
            "https://developer.x.com/en/portal/dashboard, enable OAuth 2.0 "
            "(Web App confidential client), set callback URL, and put "
            "X_CLIENT_ID and X_CLIENT_SECRET in .env. "
            "ProofPay will not simulate X authentication."
        )


def require_x_oauth() -> None:
    if not get_settings().x_oauth_configured:
        raise XOAuthNotConfigured()


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifier, challenge


def build_authorize_url(*, state: str, code_challenge: str) -> str:
    require_x_oauth()
    s = get_settings()
    params = {
        "response_type": "code",
        "client_id": s.x_client_id,
        "redirect_uri": s.x_oauth_callback_url,
        "scope": " ".join(s.oauth_scope_list),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _basic_auth_header() -> str:
    s = get_settings()
    raw = f"{s.x_client_id}:{s.x_client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def exchange_code(*, code: str, code_verifier: str) -> dict[str, Any]:
    require_x_oauth()
    s = get_settings()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": s.x_oauth_callback_url,
        "code_verifier": code_verifier,
        "client_id": s.x_client_id,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": _basic_auth_header(),
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"X token exchange failed ({resp.status_code}): {resp.text}")
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    require_x_oauth()
    s = get_settings()
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": s.x_client_id,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": _basic_auth_header(),
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"X token refresh failed ({resp.status_code}): {resp.text}")
        return resp.json()


async def fetch_me(access_token: str) -> dict[str, Any]:
    params = {
        "user.fields": "id,name,username,profile_image_url,verified",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            ME_URL,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"X /users/me failed ({resp.status_code}): {resp.text}")
        body = resp.json()
        return body.get("data") or body


def token_expiry(expires_in: Optional[int]) -> Optional[datetime]:
    if not expires_in:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in) - 60)
