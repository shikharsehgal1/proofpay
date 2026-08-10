"""Opportunity scanner — recent tweets from curated accounts."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ReplyAppJobSource, ReplyAppJobStatus
from app.services.reply_app.intent import score_opportunity
from app.services.reply_app.pipeline import create_job, run_job
from app.services import x_client


def _build_from_query(usernames: list[str]) -> str:
    # X recent search: group from: clauses
    parts = [f"from:{u}" for u in usernames[:20]]  # keep query under limits
    inner = " OR ".join(parts)
    return f"({inner}) -is:retweet -is:reply lang:en"


async def fetch_watchlist_tweets(
    *,
    usernames: Optional[list[str]] = None,
    max_results: int = 40,
) -> dict[str, Any]:
    """
    Real X recent-search for watchlist accounts.
    Prefers app bearer; falls back to bot user token.
    """
    settings = get_settings()
    users = usernames or settings.reply_app_scan_account_list
    if not users:
        return {"data": [], "error": "empty_watchlist"}

    query = _build_from_query(users)
    token = settings.x_bearer_token or settings.reply_app_bot_access_token
    if not token:
        return {
            "data": [],
            "error": "No X_BEARER_TOKEN or REPLY_APP_BOT_ACCESS_TOKEN for search",
            "query": query,
        }

    try:
        resp = await x_client.search_recent(
            query,
            max_results=max_results,
            bearer=token if settings.x_bearer_token else None,
            access_token=None if settings.x_bearer_token else settings.reply_app_bot_access_token,
        )
        resp["_query"] = query
        return resp
    except Exception as e:
        return {"data": [], "error": str(e), "query": query}


async def scan_opportunities(
    db: AsyncSession,
    *,
    usernames: Optional[list[str]] = None,
    max_results: Optional[int] = None,
    min_score: Optional[float] = None,
    auto_reply: Optional[bool] = None,
    run_now: bool = False,
) -> dict[str, Any]:
    """
    Scan watchlist → score with Grok → create draft (or queued) jobs.
    Does not post unless auto_reply and bot configured and run_now.
    """
    settings = get_settings()
    if not settings.reply_app_scan_enabled:
        return {"ok": False, "error": "scan_disabled"}

    min_score = min_score if min_score is not None else settings.reply_app_scan_min_score
    auto_reply = settings.reply_app_scan_auto_reply if auto_reply is None else auto_reply
    max_results = max_results or settings.reply_app_scan_max_tweets

    raw = await fetch_watchlist_tweets(usernames=usernames, max_results=max_results)
    tweets = raw.get("data") or []
    users = {u["id"]: u for u in (raw.get("includes") or {}).get("users") or []}

    scored: list[dict[str, Any]] = []
    created = 0
    skipped = 0

    for t in tweets:
        tid = str(t.get("id") or "")
        text = t.get("text") or ""
        author_id = str(t.get("author_id") or "")
        author = users.get(author_id, {})
        username = author.get("username")

        # Skip bot's own posts
        if settings.reply_app_bot_x_user_id and author_id == settings.reply_app_bot_x_user_id:
            skipped += 1
            continue

        opp = await score_opportunity(tweet_text=text, author_username=username)
        entry = {
            "tweet_id": tid,
            "username": username,
            "text": text[:280],
            "score": opp["score"],
            "reason": opp.get("reason"),
            "title": opp.get("title"),
        }
        scored.append(entry)

        if opp["score"] < min_score or not opp.get("brief"):
            skipped += 1
            continue

        status = (
            ReplyAppJobStatus.QUEUED
            if auto_reply and settings.reply_app_bot_configured
            else ReplyAppJobStatus.DRAFT
        )
        job = await create_job(
            db,
            source=ReplyAppJobSource.OPPORTUNITY,
            source_tweet_id=tid or None,
            source_tweet_text=text,
            source_author_id=author_id or None,
            source_author_username=username,
            conversation_id=str(t.get("conversation_id") or tid or "") or None,
            status=status,
            opportunity_score=float(opp["score"]),
            intent_json={
                "ok": True,
                "title": opp.get("title") or "Mini app",
                "brief": opp.get("brief"),
                "app_type": "utility",
                "opportunity_reason": opp.get("reason"),
                "score": opp["score"],
            },
        )
        created += 1
        entry["job_id"] = str(job.id)
        entry["job_status"] = job.status.value

        if run_now and job.status == ReplyAppJobStatus.QUEUED:
            await run_job(db, job.id, post_reply=bool(auto_reply))

    scored.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return {
        "ok": True,
        "query": raw.get("_query") or raw.get("query"),
        "search_error": raw.get("error"),
        "tweets_seen": len(tweets),
        "jobs_created_or_existing": created,
        "skipped": skipped,
        "min_score": min_score,
        "auto_reply": auto_reply,
        "top": scored[:15],
    }
