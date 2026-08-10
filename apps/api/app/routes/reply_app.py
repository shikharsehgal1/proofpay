"""HTTP API for the Grok Reply App Bot."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import ReplyApp, ReplyAppJob, ReplyAppJobSource, ReplyAppJobStatus
from app.services.reply_app.pipeline import create_job, dry_run_from_text, run_job
from app.services.reply_app.publisher import app_public_url
from app.services.reply_app.scanner import scan_opportunities
from app.services import x_client

router = APIRouter(prefix="/reply-app", tags=["reply-app"])


class DryRunBody(BaseModel):
    text: str = Field(min_length=3, max_length=4000)
    author_username: Optional[str] = None


class CreateJobBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    source_tweet_id: Optional[str] = None
    source_author_id: Optional[str] = None
    source_author_username: Optional[str] = None
    conversation_id: Optional[str] = None
    source: str = "manual"
    run_immediately: bool = True
    post_reply: bool = False  # default off until bot account wired


class ScanBody(BaseModel):
    accounts: Optional[list[str]] = None
    max_results: Optional[int] = Field(default=None, ge=10, le=100)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    auto_reply: Optional[bool] = None
    run_now: bool = False


def _job_out(job: ReplyAppJob) -> dict[str, Any]:
    app = job.app
    return {
        "id": str(job.id),
        "source": job.source.value if job.source else None,
        "status": job.status.value if job.status else None,
        "source_tweet_id": job.source_tweet_id,
        "source_tweet_text": job.source_tweet_text,
        "source_author_username": job.source_author_username,
        "opportunity_score": job.opportunity_score,
        "intent": job.intent_json,
        "skip_reason": job.skip_reason,
        "error_message": job.error_message,
        "reply_tweet_id": job.reply_tweet_id,
        "reply_tweet_url": job.reply_tweet_url,
        "app": {
            "id": str(app.id),
            "slug": app.public_slug,
            "title": app.title,
            "url": app_public_url(app.public_slug),
            "summary": app.summary,
        }
        if app
        else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/status")
async def status():
    s = get_settings()
    return {
        "product": "grok_reply_app_bot",
        "enabled": s.reply_app_bot_enabled,
        "bot_configured": s.reply_app_bot_configured,
        "bot_username": s.reply_app_bot_x_username or None,
        "bot_user_id_set": bool(s.reply_app_bot_x_user_id),
        "access_token_set": bool(s.reply_app_bot_access_token),
        "xai_configured": s.xai_configured,
        "attach_preview_image": s.reply_app_attach_preview_image,
        "scan": {
            "enabled": s.reply_app_scan_enabled,
            "auto_reply": s.reply_app_scan_auto_reply,
            "min_score": s.reply_app_scan_min_score,
            "accounts": s.reply_app_scan_account_list,
            "bearer_or_bot_for_search": bool(s.x_bearer_token or s.reply_app_bot_access_token),
        },
        "app_base_url": s.app_base_url,
        "ready_for_dry_run": s.xai_configured,
        "ready_for_live_replies": s.reply_app_bot_configured and s.xai_configured,
        "docs": "/docs#/reply-app",
        "architecture": "docs/REPLY_APP_BOT.md",
    }


@router.post("/dry-run")
async def dry_run(body: DryRunBody, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    if not s.xai_configured:
        raise HTTPException(503, "XAI_API_KEY required for generation")
    return await dry_run_from_text(db, body.text, author_username=body.author_username)


@router.post("/jobs")
async def create_and_maybe_run(
    body: CreateJobBody,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    try:
        source = ReplyAppJobSource(body.source)
    except ValueError:
        source = ReplyAppJobSource.MANUAL

    job = await create_job(
        db,
        source=source,
        source_tweet_id=body.source_tweet_id,
        source_tweet_text=body.text,
        source_author_id=body.source_author_id,
        source_author_username=body.source_author_username,
        conversation_id=body.conversation_id,
        status=ReplyAppJobStatus.QUEUED,
    )

    if body.run_immediately:
        job = await run_job(db, job.id, post_reply=body.post_reply)
    else:
        async def _bg(jid: UUID, post: bool):
            async with SessionLocal() as session:
                await run_job(session, jid, post_reply=post)

        background.add_task(_bg, job.id, body.post_reply)

    r = await db.execute(
        select(ReplyAppJob).options(selectinload(ReplyAppJob.app)).where(ReplyAppJob.id == job.id)
    )
    return _job_out(r.scalar_one())


@router.post("/jobs/{job_id}/run")
async def run_existing(
    job_id: UUID,
    post_reply: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ReplyAppJob).where(ReplyAppJob.id == job_id))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "job not found")
    job = await run_job(db, job_id, post_reply=post_reply)
    r = await db.execute(
        select(ReplyAppJob).options(selectinload(ReplyAppJob.app)).where(ReplyAppJob.id == job.id)
    )
    return _job_out(r.scalar_one())


@router.get("/jobs")
async def list_jobs(
    limit: int = Query(30, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(ReplyAppJob).options(selectinload(ReplyAppJob.app)).order_by(ReplyAppJob.created_at.desc()).limit(limit)
    if status:
        try:
            st = ReplyAppJobStatus(status)
            q = q.where(ReplyAppJob.status == st)
        except ValueError:
            raise HTTPException(400, f"invalid status {status}")
    r = await db.execute(q)
    return [_job_out(j) for j in r.scalars().all()]


@router.get("/apps/{slug}")
async def get_app_meta(slug: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ReplyApp).where(ReplyApp.public_slug == slug))
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "app not found")
    return {
        "id": str(app.id),
        "slug": app.public_slug,
        "title": app.title,
        "summary": app.summary,
        "url": app_public_url(app.public_slug),
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }


@router.get("/apps/{slug}/html", response_class=HTMLResponse)
async def get_app_html(slug: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ReplyApp).where(ReplyApp.public_slug == slug))
    app = r.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "app not found")
    return HTMLResponse(content=app.html, status_code=200)


@router.post("/poll-mentions")
async def poll_mentions(
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    max_results: int = Query(25, ge=5, le=100),
    run: bool = Query(True),
    post_reply: bool = Query(True),
):
    """
    Pull bot mentions via X API and enqueue reply-app jobs.
    Requires REPLY_APP_BOT_* credentials.
    """
    s = get_settings()
    if not s.reply_app_bot_configured:
        raise HTTPException(
            503,
            "Bot not configured. Set REPLY_APP_BOT_ENABLED, REPLY_APP_BOT_X_USER_ID, "
            "REPLY_APP_BOT_ACCESS_TOKEN (dedicated bot account).",
        )

    try:
        resp = await x_client.get_user_mentions(
            s.reply_app_bot_x_user_id,
            access_token=s.reply_app_bot_access_token,
            max_results=max_results,
        )
    except Exception as e:
        raise HTTPException(502, f"X mentions API error: {e}") from e

    tweets = resp.get("data") or []
    users = {u["id"]: u for u in (resp.get("includes") or {}).get("users") or []}
    # referenced tweets may include parent
    ref_tweets = {t["id"]: t for t in (resp.get("includes") or {}).get("tweets") or []}

    enqueued = 0
    jobs_out = []
    for t in tweets:
        mention_id = str(t.get("id") or "")
        author_id = str(t.get("author_id") or "")
        author = users.get(author_id, {})
        parent_id = await x_client.get_referenced_parent_id(t)
        # Reply under the parent if this is a mention-as-reply; else under the mention itself
        source_id = parent_id or mention_id
        source_text = t.get("text") or ""
        if parent_id and parent_id in ref_tweets:
            # Prefer parent context + mention instruction
            parent_text = ref_tweets[parent_id].get("text") or ""
            source_text = f"{parent_text}\n\n---\nMention: {source_text}"

        job = await create_job(
            db,
            source=ReplyAppJobSource.MENTION,
            source_tweet_id=source_id,
            source_tweet_text=source_text,
            source_author_id=author_id,
            source_author_username=author.get("username"),
            conversation_id=str(t.get("conversation_id") or source_id),
            mention_tweet_id=mention_id,
            status=ReplyAppJobStatus.QUEUED,
        )
        enqueued += 1
        if run:
            job = await run_job(db, job.id, post_reply=post_reply)
        r = await db.execute(
            select(ReplyAppJob).options(selectinload(ReplyAppJob.app)).where(ReplyAppJob.id == job.id)
        )
        jobs_out.append(_job_out(r.scalar_one()))

    return {
        "mentions_seen": len(tweets),
        "jobs": jobs_out,
        "enqueued": enqueued,
    }


@router.post("/scan-opportunities")
async def scan(body: ScanBody, db: AsyncSession = Depends(get_db)):
    """
    Initial / recurring scan of recent tweets from top accounts.
    Creates draft jobs by default (no auto-reply until REPLY_APP_SCAN_AUTO_REPLY=true).
    """
    s = get_settings()
    if not s.xai_configured:
        raise HTTPException(503, "XAI_API_KEY required to score opportunities")
    result = await scan_opportunities(
        db,
        usernames=body.accounts,
        max_results=body.max_results,
        min_score=body.min_score,
        auto_reply=body.auto_reply,
        run_now=body.run_now,
    )
    return result


@router.post("/scan-opportunities/run-drafts")
async def run_drafts(
    limit: int = Query(10, ge=1, le=50),
    post_reply: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Promote draft opportunity jobs through generation (and optional reply)."""
    r = await db.execute(
        select(ReplyAppJob)
        .where(
            ReplyAppJob.status == ReplyAppJobStatus.DRAFT,
            ReplyAppJob.source == ReplyAppJobSource.OPPORTUNITY,
        )
        .order_by(ReplyAppJob.opportunity_score.desc().nullslast())
        .limit(limit)
    )
    drafts = list(r.scalars().all())
    out = []
    for j in drafts:
        j.status = ReplyAppJobStatus.QUEUED
        await db.commit()
        job = await run_job(db, j.id, post_reply=post_reply)
        rr = await db.execute(
            select(ReplyAppJob).options(selectinload(ReplyAppJob.app)).where(ReplyAppJob.id == job.id)
        )
        out.append(_job_out(rr.scalar_one()))
    return {"ran": len(out), "jobs": out}
