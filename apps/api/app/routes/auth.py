from __future__ import annotations

import secrets
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth_session import clear_session, get_current_user, set_session
from app.config import get_settings
from app.crypto_tokens import encrypt_token
from app.db import get_db
from app.models import OAuthState, OAuthToken, User
from app.schemas import UserOut
from app.services import x_oauth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/x/start")
async def x_start(
    db: AsyncSession = Depends(get_db),
    redirect: Optional[str] = Query(default='/', alias='redirect'),
):
    try:
        x_oauth.require_x_oauth()
    except x_oauth.XOAuthNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    verifier, challenge = x_oauth.generate_pkce_pair()
    state = secrets.token_urlsafe(32)
    db.add(OAuthState(state=state, code_verifier=verifier, redirect_after=redirect))
    await db.commit()
    url = x_oauth.build_authorize_url(state=state, code_challenge=challenge)
    return {"authorize_url": url}


@router.get("/x/callback")
async def x_callback(
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    if error:
        return RedirectResponse(f"{settings.app_base_url}/login?error={error}")
    if not code or not state:
        raise HTTPException(400, "Missing code/state")

    r = await db.execute(select(OAuthState).where(OAuthState.state == state, OAuthState.consumed.is_(False)))
    st = r.scalar_one_or_none()
    if not st:
        raise HTTPException(400, "Invalid or expired OAuth state")
    st.consumed = True

    try:
        token_payload = await x_oauth.exchange_code(code=code, code_verifier=st.code_verifier)
    except Exception as e:
        raise HTTPException(502, f"X token exchange failed: {e}") from e

    access = token_payload["access_token"]
    refresh = token_payload.get("refresh_token")
    scope = token_payload.get("scope", "")
    expires_at = x_oauth.token_expiry(token_payload.get("expires_in"))

    try:
        me = await x_oauth.fetch_me(access)
    except Exception as e:
        raise HTTPException(502, f"X user lookup failed: {e}") from e

    x_user_id = str(me["id"])
    username = me["username"]
    display = me.get("name")
    avatar = me.get("profile_image_url")

    ur = await db.execute(
        select(User).options(selectinload(User.oauth)).where(User.x_user_id == x_user_id)
    )
    user = ur.scalar_one_or_none()
    if not user:
        user = User(
            x_user_id=x_user_id,
            x_username=username,
            display_name=display,
            profile_image_url=avatar,
        )
        db.add(user)
        await db.flush()
    else:
        user.x_username = username
        user.display_name = display
        user.profile_image_url = avatar

    if user.oauth:
        user.oauth.access_token_enc = encrypt_token(access)
        user.oauth.refresh_token_enc = encrypt_token(refresh) if refresh else None
        user.oauth.scope = scope
        user.oauth.expires_at = expires_at
    else:
        db.add(
            OAuthToken(
                user_id=user.id,
                access_token_enc=encrypt_token(access),
                refresh_token_enc=encrypt_token(refresh) if refresh else None,
                scope=scope,
                expires_at=expires_at,
            )
        )

    await db.commit()
    redirect_to = st.redirect_after or "/"
    resp = RedirectResponse(f"{settings.app_base_url}{redirect_to if redirect_to.startswith('/') else '/'}")
    set_session(resp, user.id)
    return resp


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/logout")
async def logout(response: Response):
    clear_session(response)
    return {"ok": True}
