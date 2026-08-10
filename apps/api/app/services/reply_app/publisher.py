"""Persist mini-app + reply on X under the source tweet."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ReplyApp, ReplyAppJob
from app.services.reply_app.generator import GeneratedApp
from app.services.x_client import create_post, post_url, upload_media_simple


def public_slug() -> str:
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12].lower()


def app_public_url(slug: str) -> str:
    settings = get_settings()
    return f"{settings.app_base_url.rstrip('/')}/a/{slug}"


async def persist_app(
    db: AsyncSession,
    generated: GeneratedApp,
    *,
    brief: str,
) -> ReplyApp:
    app = ReplyApp(
        public_slug=public_slug(),
        title=generated.title,
        summary=generated.summary,
        html=generated.html,
        prompt_brief=brief,
        generation_metadata=generated.metadata,
    )
    db.add(app)
    await db.flush()
    return app


async def reply_with_app(
    *,
    job: ReplyAppJob,
    app: ReplyApp,
    preview_png: Optional[bytes] = None,
) -> dict:
    """
    Post a reply under job.source_tweet_id using the dedicated bot account token.
    """
    settings = get_settings()
    if not settings.reply_app_bot_access_token:
        raise RuntimeError("REPLY_APP_BOT_ACCESS_TOKEN not configured")
    if not job.source_tweet_id:
        raise RuntimeError("Job has no source_tweet_id to reply to")

    url = app_public_url(app.public_slug)
    text = settings.reply_app_reply_template.format(url=url, title=app.title)
    if len(text) > 280:
        text = f"App → {url}"[:280]

    media_ids = None
    if preview_png:
        try:
            mid = await upload_media_simple(
                preview_png,
                access_token=settings.reply_app_bot_access_token,
            )
            media_ids = [mid]
            # also stash preview on disk
            art = Path(settings.artifacts_dir) / "reply_apps" / str(app.id)
            art.mkdir(parents=True, exist_ok=True)
            path = art / "preview.png"
            path.write_bytes(preview_png)
            app.preview_image_path = str(path)
        except Exception:
            media_ids = None

    resp = await create_post(
        text,
        access_token=settings.reply_app_bot_access_token,
        in_reply_to=job.source_tweet_id,
        media_ids=media_ids,
    )
    data = resp.get("data") or resp
    reply_id = str(data.get("id") or "")
    username = settings.reply_app_bot_x_username or "i"
    return {
        "reply_tweet_id": reply_id,
        "reply_tweet_url": post_url(username, reply_id) if reply_id else None,
        "app_url": url,
        "raw": resp,
    }
