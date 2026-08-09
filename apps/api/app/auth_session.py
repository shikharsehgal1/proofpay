"""Server-side session cookies after X OAuth. Tokens never exposed to browser JS beyond session id."""

from __future__ import annotations

import secrets
from typing import Optional
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from itsdangerous import BadSignature, URLSafeSerializer

from app.config import get_settings
from app.db import get_db
from app.models import User

COOKIE_NAME = "proofpay_session"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="proofpay-session")


def set_session(response: Response, user_id: UUID) -> None:
    token = _serializer().dumps({"uid": str(user_id), "n": secrets.token_hex(8)})
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=get_settings().app_env != "development",
        max_age=60 * 60 * 24 * 14,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read_user_id(cookie: Optional[str]) -> Optional[UUID]:
    if not cookie:
        return None
    try:
        data = _serializer().loads(cookie)
        return UUID(data["uid"])
    except (BadSignature, KeyError, ValueError):
        return None


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    proofpay_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    uid = read_user_id(proofpay_session)
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    r = await db.execute(
        select(User).options(selectinload(User.oauth)).where(User.id == uid)
    )
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_optional_user(
    db: AsyncSession = Depends(get_db),
    proofpay_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
) -> Optional[User]:
    uid = read_user_id(proofpay_session)
    if not uid:
        return None
    r = await db.execute(
        select(User).options(selectinload(User.oauth)).where(User.id == uid)
    )
    return r.scalar_one_or_none()
