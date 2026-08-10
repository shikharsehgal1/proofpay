"""Real X webhook endpoints — CRC + event ingest. No synthetic event injection."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import Bounty, BountyStatus, XWebhookEvent
from app.services.bounty_service import ingest_reply_submission, log_event
from app.services.eval_pipeline import run_evaluation_job
from app.services.x_client import crc_response_token, extract_github_urls, verify_webhook_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/x")
async def x_crc(crc_token: str = Query(alias="crc_token")):
    """
    X webhook Challenge-Response Check.
    Uses X_WEBHOOK_CRC_SECRET or X_API_SECRET / X_CLIENT_SECRET.
    """
    s = get_settings()
    secret = s.x_webhook_crc_secret or s.x_api_secret or s.x_client_secret
    if not secret:
        raise HTTPException(
            503,
            "Webhook CRC secret not configured. Set X_WEBHOOK_CRC_SECRET or X_API_SECRET.",
        )
    return {"response_token": crc_response_token(crc_token, secret)}


@router.post("/x")
async def x_events(
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    s = get_settings()
    secret = s.x_webhook_crc_secret or s.x_api_secret or s.x_client_secret
    sig = request.headers.get("x-twitter-webhooks-signature") or request.headers.get(
        "X-Twitter-Webhooks-Signature"
    )
    # In development without secret, refuse silently-faked path — require config
    if s.app_env != "development":
        if not secret or not verify_webhook_signature(sig, body, secret):
            raise HTTPException(401, "Invalid webhook signature")
    elif secret and sig and not verify_webhook_signature(sig, body, secret):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        payload = json.loads(body.decode() or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, "Invalid JSON") from e

    event_id = str(
        payload.get("id")
        or payload.get("event_id")
        or hash(body) & 0xFFFFFFFFFFFFFFFF
    )
    existing = await db.execute(select(XWebhookEvent).where(XWebhookEvent.event_id == event_id))
    if existing.scalar_one_or_none():
        return {"ok": True, "deduped": True}

    event_type = str(payload.get("event_type") or payload.get("type") or "unknown")
    db.add(
        XWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            processed=False,
        )
    )
    await db.commit()

    background.add_task(_process_payload, payload)
    return {"ok": True}


async def _process_payload(payload: dict[str, Any]) -> None:
    """Extract posts/replies → ProofPay bounties and/or Reply App Bot mentions."""
    posts = _extract_posts(payload)
    settings = get_settings()
    bot_user = (settings.reply_app_bot_x_username or "").lower().lstrip("@")
    bot_id = settings.reply_app_bot_x_user_id

    async with SessionLocal() as db:
        for post in posts:
            text = post.get("text") or ""
            post_id = str(post.get("id") or "")
            author_id = str(post.get("author_id") or post.get("author", {}).get("id") or "")
            username = post.get("username") or post.get("author", {}).get("username")
            conversation_id = str(post.get("conversation_id") or "")
            referenced = post.get("referenced_tweets") or []
            parent_ids = [str(r.get("id")) for r in referenced if r.get("type") in ("replied_to", "quote")]

            # ── Reply App Bot: @mention of dedicated bot account ──
            text_l = text.lower()
            is_bot_mention = bool(bot_user and f"@{bot_user}" in text_l)
            if settings.reply_app_bot_enabled and is_bot_mention and author_id != bot_id:
                try:
                    from app.models import ReplyAppJobSource, ReplyAppJobStatus
                    from app.services.reply_app.pipeline import create_job, run_job

                    parent = parent_ids[0] if parent_ids else post_id
                    job = await create_job(
                        db,
                        source=ReplyAppJobSource.MENTION,
                        source_tweet_id=parent,
                        source_tweet_text=text,
                        source_author_id=author_id or None,
                        source_author_username=username,
                        conversation_id=conversation_id or parent,
                        mention_tweet_id=post_id,
                        status=ReplyAppJobStatus.QUEUED,
                    )
                    await run_job(db, job.id, post_reply=True)
                except Exception:
                    pass  # bounty path may still apply

            if not extract_github_urls(text):
                continue

            # Match bounty by conversation or parent
            q = await db.execute(
                select(Bounty).where(
                    Bounty.status.in_(
                        [BountyStatus.PUBLISHED, BountyStatus.EVALUATING, BountyStatus.RANKED]
                    )
                )
            )
            bounties = list(q.scalars().all())
            matched: Optional[Bounty] = None
            for b in bounties:
                if b.conversation_id and b.conversation_id == conversation_id:
                    matched = b
                    break
                if b.x_post_id and (b.x_post_id in parent_ids or b.x_post_id == conversation_id):
                    matched = b
                    break
            if not matched:
                continue

            sub = await ingest_reply_submission(
                db,
                bounty=matched,
                reply_id=post_id,
                reply_text=text,
                author_id=author_id or None,
                author_username=username,
            )
            if sub:
                await run_evaluation_job(db, sub.id)


def _extract_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize X Activity / AAA / generic webhook shapes into post dicts."""
    posts: list[dict[str, Any]] = []
    if "post" in payload and isinstance(payload["post"], dict):
        posts.append(payload["post"])
    if "data" in payload and isinstance(payload["data"], dict) and payload["data"].get("text"):
        posts.append(payload["data"])
    if "tweet_create_events" in payload:
        for t in payload["tweet_create_events"]:
            posts.append(
                {
                    "id": t.get("id_str") or t.get("id"),
                    "text": t.get("text"),
                    "author_id": str((t.get("user") or {}).get("id_str") or (t.get("user") or {}).get("id") or ""),
                    "username": (t.get("user") or {}).get("screen_name"),
                    "conversation_id": t.get("conversation_id")
                    or (t.get("in_reply_to_status_id_str")),
                }
            )
    # X Activity event envelope
    event = payload.get("event") or payload
    if event.get("event_type") in ("post.create", "post.mention.create") or payload.get(
        "event_type"
    ) in ("post.create", "post.mention.create"):
        data = payload.get("data") or event.get("data") or {}
        if data:
            posts.append(data)
    return posts


@router.post("/x/poll-conversations")
async def poll_conversations(
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Real X recent-search poll for published bounty conversations.
    Used when push webhooks are not yet reachable — still live API, not fixtures.
    """
    from app.services.x_client import search_conversation_replies

    r = await db.execute(
        select(Bounty).where(
            Bounty.x_post_id.is_not(None),
            Bounty.status.in_(
                [BountyStatus.PUBLISHED, BountyStatus.EVALUATING, BountyStatus.RANKED]
            ),
        )
    )
    bounties = list(r.scalars().all())
    found = 0
    errors = []
    for b in bounties:
        if not b.conversation_id and not b.x_post_id:
            continue
        cid = b.conversation_id or b.x_post_id
        try:
            resp = await search_conversation_replies(cid)
        except Exception as e:
            errors.append({"bounty": str(b.id), "error": str(e)})
            continue
        data = resp.get("data") or []
        users = {u["id"]: u for u in (resp.get("includes") or {}).get("users") or []}
        for post in data:
            if str(post.get("id")) == str(b.x_post_id):
                continue
            author = users.get(post.get("author_id"), {})
            sub = await ingest_reply_submission(
                db,
                bounty=b,
                reply_id=str(post["id"]),
                reply_text=post.get("text") or "",
                author_id=str(post.get("author_id") or ""),
                author_username=author.get("username"),
            )
            if sub:
                found += 1
                await run_evaluation_job(db, sub.id)
    return {"polled": len(bounties), "new_submissions": found, "errors": errors}
