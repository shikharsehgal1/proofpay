"""End-to-end Reply App job runner."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import ReplyAppJob, ReplyAppJobSource, ReplyAppJobStatus
from app.services.reply_app.generator import generate_html_app, maybe_preview_image
from app.services.reply_app.intent import AppIntent, parse_intent
from app.services.reply_app.publisher import app_public_url, persist_app, reply_with_app


async def _rate_limit_ok(db: AsyncSession) -> bool:
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    r = await db.execute(
        select(func.count())
        .select_from(ReplyAppJob)
        .where(
            ReplyAppJob.created_at >= since,
            ReplyAppJob.status.in_(
                [
                    ReplyAppJobStatus.RUNNING,
                    ReplyAppJobStatus.GENERATED,
                    ReplyAppJobStatus.REPLIED,
                ]
            ),
        )
    )
    n = int(r.scalar_one() or 0)
    return n < settings.reply_app_max_jobs_per_hour


async def create_job(
    db: AsyncSession,
    *,
    source: ReplyAppJobSource,
    source_tweet_id: Optional[str] = None,
    source_tweet_text: str,
    source_author_id: Optional[str] = None,
    source_author_username: Optional[str] = None,
    conversation_id: Optional[str] = None,
    mention_tweet_id: Optional[str] = None,
    status: ReplyAppJobStatus = ReplyAppJobStatus.QUEUED,
    opportunity_score: Optional[float] = None,
    intent_json: Optional[dict] = None,
) -> ReplyAppJob:
    if source_tweet_id:
        existing = await db.execute(
            select(ReplyAppJob).where(ReplyAppJob.source_tweet_id == source_tweet_id)
        )
        found = existing.scalar_one_or_none()
        if found:
            return found

    job = ReplyAppJob(
        source=source,
        status=status,
        source_tweet_id=source_tweet_id,
        source_tweet_text=source_tweet_text,
        source_author_id=source_author_id,
        source_author_username=source_author_username,
        conversation_id=conversation_id,
        mention_tweet_id=mention_tweet_id,
        opportunity_score=opportunity_score,
        intent_json=intent_json,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def dry_run_from_text(
    db: AsyncSession,
    text: str,
    *,
    author_username: Optional[str] = None,
) -> dict[str, Any]:
    """Intent + HTML generation without X side effects."""
    settings = get_settings()
    intent = await parse_intent(
        tweet_text=text,
        author_username=author_username,
        bot_username=settings.reply_app_bot_x_username,
        source="dry_run",
    )
    if not intent.ok:
        return {"ok": False, "intent": intent.as_dict}

    gen = await generate_html_app(intent)
    app = await persist_app(db, gen, brief=intent.brief)
    await db.commit()
    await db.refresh(app)

    job = await create_job(
        db,
        source=ReplyAppJobSource.DRY_RUN,
        source_tweet_text=text,
        source_author_username=author_username,
        status=ReplyAppJobStatus.GENERATED,
        intent_json=intent.as_dict,
    )
    job.app_id = app.id
    job.finished_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "ok": True,
        "intent": intent.as_dict,
        "app": {
            "id": str(app.id),
            "slug": app.public_slug,
            "url": app_public_url(app.public_slug),
            "title": app.title,
            "html_bytes": len(app.html),
        },
        "job_id": str(job.id),
    }


async def run_job(
    db: AsyncSession,
    job_id: UUID,
    *,
    post_reply: bool = True,
) -> ReplyAppJob:
    settings = get_settings()
    r = await db.execute(
        select(ReplyAppJob).options(selectinload(ReplyAppJob.app)).where(ReplyAppJob.id == job_id)
    )
    job = r.scalar_one()

    if job.status in (ReplyAppJobStatus.REPLIED, ReplyAppJobStatus.SKIPPED):
        return job

    if not await _rate_limit_ok(db):
        job.status = ReplyAppJobStatus.SKIPPED
        job.skip_reason = "rate_limit"
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return job

    # Skip replies to ourselves
    if (
        settings.reply_app_bot_x_user_id
        and job.source_author_id
        and job.source_author_id == settings.reply_app_bot_x_user_id
    ):
        job.status = ReplyAppJobStatus.SKIPPED
        job.skip_reason = "self_author"
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return job

    job.status = ReplyAppJobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    job.error_message = None
    await db.commit()

    try:
        if job.intent_json and job.intent_json.get("ok") and job.intent_json.get("brief"):
            intent = AppIntent(
                ok=True,
                title=str(job.intent_json.get("title") or "Mini app"),
                brief=str(job.intent_json.get("brief")),
                app_type=str(job.intent_json.get("app_type") or "utility"),
                raw=job.intent_json,
            )
        else:
            intent = await parse_intent(
                tweet_text=job.source_tweet_text or "",
                author_username=job.source_author_username,
                bot_username=settings.reply_app_bot_x_username,
                source=job.source.value if job.source else "mention",
            )
            job.intent_json = intent.as_dict

        if not intent.ok:
            job.status = ReplyAppJobStatus.SKIPPED
            job.skip_reason = intent.refuse_reason or "intent_refused"
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return job

        gen = await generate_html_app(intent)
        app = await persist_app(db, gen, brief=intent.brief)
        job.app_id = app.id
        job.status = ReplyAppJobStatus.GENERATED
        await db.commit()

        if post_reply and job.source_tweet_id and settings.reply_app_bot_configured:
            preview = await maybe_preview_image(intent.title, intent.brief)
            result = await reply_with_app(job=job, app=app, preview_png=preview)
            job.reply_tweet_id = result.get("reply_tweet_id")
            job.reply_tweet_url = result.get("reply_tweet_url")
            job.status = ReplyAppJobStatus.REPLIED
        elif post_reply and not settings.reply_app_bot_configured:
            # Architecture ready: leave as GENERATED until bot tokens exist
            job.skip_reason = "bot_not_configured_left_generated"
        elif post_reply and not job.source_tweet_id:
            job.skip_reason = "no_source_tweet_id"

        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)
        return job
    except Exception as e:
        job.status = ReplyAppJobStatus.FAILED
        job.error_message = str(e)[:2000]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(job)
        return job
