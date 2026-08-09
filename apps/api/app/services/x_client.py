"""Real X API v2 client — posts, replies, media, conversation lookup. No synthetic events."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

import httpx

from app.config import get_settings

API = "https://api.x.com/2"
UPLOAD = "https://api.x.com/2/media/upload"


class XAPIError(RuntimeError):
    pass


async def _request(
    method: str,
    path: str,
    *,
    access_token: Optional[str] = None,
    bearer: Optional[str] = None,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
    data: Optional[dict] = None,
    files: Optional[dict] = None,
    base: str = API,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    token = access_token or bearer
    if not token:
        s = get_settings()
        token = s.x_bearer_token
    if not token:
        raise XAPIError(
            "No X access token available. Authenticate a user via OAuth or set X_BEARER_TOKEN."
        )
    headers["Authorization"] = f"Bearer {token}"
    url = path if path.startswith("http") else f"{base}{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            data=data,
            files=files,
        )
        if resp.status_code >= 400:
            raise XAPIError(f"X API {method} {path} → {resp.status_code}: {resp.text}")
        if not resp.content:
            return {}
        return resp.json()


async def create_post(
    text: str,
    *,
    access_token: str,
    in_reply_to: Optional[str] = None,
    media_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"text": text}
    if in_reply_to:
        body["reply"] = {"in_reply_to_tweet_id": in_reply_to}
    if media_ids:
        body["media"] = {"media_ids": media_ids}
    return await _request("POST", "/tweets", access_token=access_token, json_body=body)


async def get_post(post_id: str, *, access_token: Optional[str] = None) -> dict[str, Any]:
    params = {
        "tweet.fields": "author_id,conversation_id,created_at,text,public_metrics,in_reply_to_user_id",
        "expansions": "author_id",
        "user.fields": "username,name,profile_image_url",
    }
    return await _request("GET", f"/tweets/{post_id}", access_token=access_token, params=params)


async def search_conversation_replies(
    conversation_id: str,
    *,
    access_token: Optional[str] = None,
    max_results: int = 50,
) -> dict[str, Any]:
    """
    Real recent-search for replies in a conversation.
    Requires search access on the app tier — will raise XAPIError if unavailable.
    """
    query = f"conversation_id:{conversation_id} -is:retweet"
    params = {
        "query": query,
        "max_results": str(min(max(10, max_results), 100)),
        "tweet.fields": "author_id,conversation_id,created_at,text,in_reply_to_user_id,referenced_tweets",
        "expansions": "author_id",
        "user.fields": "username,name,profile_image_url",
    }
    return await _request(
        "GET",
        "/tweets/search/recent",
        access_token=access_token,
        params=params,
    )


async def upload_media_simple(
    image_bytes: bytes,
    *,
    access_token: str,
    media_type: str = "image/png",
) -> str:
    """
    Simple media upload for images (non-chunked).
    Requires media.write scope on the user token.
    """
    # v2 media upload INIT/APPEND/FINALIZE for reliability
    total = len(image_bytes)
    init = await _request(
        "POST",
        "/media/upload",
        access_token=access_token,
        data={
            "command": "INIT",
            "media_type": media_type,
            "total_bytes": str(total),
            "media_category": "tweet_image",
        },
        base=API,
    )
    # Some deployments return media_id under data
    media_id = str(
        init.get("media_id_string")
        or init.get("media_id")
        or (init.get("data") or {}).get("id")
        or (init.get("data") or {}).get("media_id")
    )
    if not media_id or media_id == "None":
        raise XAPIError(f"Media INIT did not return media_id: {init}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{API}/media/upload",
            headers={"Authorization": f"Bearer {access_token}"},
            data={"command": "APPEND", "media_id": media_id, "segment_index": "0"},
            files={"media": ("image.png", image_bytes, media_type)},
        )
        if resp.status_code >= 400:
            raise XAPIError(f"Media APPEND failed: {resp.status_code} {resp.text}")

    finalized = await _request(
        "POST",
        "/media/upload",
        access_token=access_token,
        data={"command": "FINALIZE", "media_id": media_id},
    )
    mid = str(
        finalized.get("media_id_string")
        or finalized.get("media_id")
        or media_id
    )
    return mid


def crc_response_token(crc_token: str, consumer_secret: str) -> str:
    """Challenge-Response Check for X webhooks."""
    digest = hmac.new(
        consumer_secret.encode("utf-8"),
        crc_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    import base64

    return "sha256=" + base64.b64encode(digest).decode()


def verify_webhook_signature(
    signature_header: Optional[str],
    body: bytes,
    consumer_secret: str,
) -> bool:
    """
    Verify X-Twitter-Webhooks-Signature (or current X equivalent header).
    Returns False if signature missing/invalid — never accept unsigned production webhooks blindly.
    """
    if not signature_header:
        return False
    expected = "sha256=" + __import__("base64").b64encode(
        hmac.new(consumer_secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header)


async def register_webhook(url: str, *, bearer: Optional[str] = None) -> dict[str, Any]:
    """Register webhook URL with X Webhooks API (app-only)."""
    return await _request(
        "POST",
        "/webhooks",
        bearer=bearer or get_settings().x_bearer_token,
        json_body={"url": url},
    )


async def create_activity_subscription(
    *,
    event_types: list[str],
    user_id: str,
    webhook_url: Optional[str] = None,
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create X Activity API subscription.
    Exact payload may vary by tier — surfaces real API errors if unavailable.
    """
    body: dict[str, Any] = {
        "event_types": event_types,
        "filters": [{"user_id": user_id}],
    }
    if webhook_url:
        body["delivery"] = {"type": "webhook", "url": webhook_url}
    return await _request(
        "POST",
        "/activity/subscriptions",
        access_token=access_token,
        bearer=get_settings().x_bearer_token if not access_token else None,
        json_body=body,
    )


def post_url(username: str, post_id: str) -> str:
    return f"https://x.com/{username}/status/{post_id}"


def extract_github_urls(text: str) -> list[str]:
    import re

    pattern = r"https?://(?:www\.)?github\.com/[^\s\)\]\>]+"
    return re.findall(pattern, text or "")
