"""Parse a tweet / mention into a safe app brief via Grok."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services import xai_client


@dataclass
class AppIntent:
    ok: bool
    title: str = ""
    brief: str = ""
    app_type: str = "utility"  # utility | calculator | form | checklist | converter | game | other
    refuse_reason: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "title": self.title,
            "brief": self.brief,
            "app_type": self.app_type,
            "refuse_reason": self.refuse_reason,
            **{k: v for k, v in self.raw.items() if k not in ("ok", "title", "brief", "app_type", "refuse_reason")},
        }


_BOT_MENTION_RE = re.compile(r"@\w+", re.I)


def strip_mentions(text: str, bot_username: str = "") -> str:
    t = text or ""
    if bot_username:
        t = re.sub(rf"@{re.escape(bot_username)}\b", "", t, flags=re.I)
    t = _BOT_MENTION_RE.sub("", t)
    return " ".join(t.split()).strip()


async def parse_intent(
    *,
    tweet_text: str,
    author_username: Optional[str] = None,
    bot_username: str = "",
    source: str = "mention",
) -> AppIntent:
    """
    Structured intent from Grok. Refuses unsafe / non-app requests.
    """
    cleaned = strip_mentions(tweet_text, bot_username)
    if not cleaned and source == "mention":
        cleaned = "Build a small useful utility app inspired by a generic productivity need."

    system = (
        "You are the intent compiler for a Grok Reply App Bot. "
        "Given a tweet, decide if we should build a tiny single-page web app in reply. "
        "Return ONLY JSON with keys: "
        "ok (bool), title (short), brief (1-3 sentences of product requirements), "
        "app_type (utility|calculator|form|checklist|converter|game|other), "
        "refuse_reason (string|null). "
        "Set ok=false for: scams, phishing, malware, weapons, adult/CSAM, medical diagnosis, "
        "hate, doxxing, credential harvesting, or requests that need server-side secrets/auth. "
        "Prefer concrete interactive tools (calculators, planners, converters, checklists, "
        "mini dashboards with localStorage). Keep scope tiny enough for one HTML file."
    )
    user = json.dumps(
        {
            "tweet_text": tweet_text,
            "cleaned_request": cleaned,
            "author_username": author_username,
            "source": source,
        },
        indent=2,
    )

    try:
        content = await xai_client.chat_text(system, user + "\n\nRespond with a single JSON object.", temperature=0.15)
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        data = json.loads(content)
    except Exception as e:
        return AppIntent(ok=False, refuse_reason=f"intent_parse_failed: {e}")

    ok = bool(data.get("ok", False))
    title = str(data.get("title") or "Mini app").strip()[:120]
    brief = str(data.get("brief") or cleaned).strip()[:2000]
    app_type = str(data.get("app_type") or "utility")
    refuse = data.get("refuse_reason")
    if not ok:
        return AppIntent(
            ok=False,
            title=title,
            brief=brief,
            app_type=app_type,
            refuse_reason=str(refuse or "refused"),
            raw=data,
        )
    if not brief:
        return AppIntent(ok=False, refuse_reason="empty_brief", raw=data)
    return AppIntent(ok=True, title=title, brief=brief, app_type=app_type, raw=data)


async def score_opportunity(
    *,
    tweet_text: str,
    author_username: Optional[str] = None,
) -> dict[str, Any]:
    """
    Score whether a public tweet is a good candidate for an unsolicited helpful mini-app reply.
    Returns: {score: float 0-1, ok: bool, title, brief, reason}
    """
    system = (
        "You score tweets for a helpful Grok mini-app reply bot. "
        "High score only if a tiny interactive web app would clearly help the author or readers "
        "(e.g. calculator, checklist, converter, planner, ROI tool, name generator tied to the ask). "
        "Low score for pure news, vague vibes, dunks, politics flamewars, already-complete threads, "
        "or when a reply would feel spammy. "
        "Return ONLY JSON: score (0-1), ok (bool, true if score>=0.7 conceptually), "
        "title, brief (app to build), reason (short)."
    )
    user = json.dumps({"tweet_text": tweet_text, "author_username": author_username}, indent=2)
    try:
        content = await xai_client.chat_text(system, user + "\n\nJSON only.", temperature=0.1)
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        data = json.loads(content)
        score = float(data.get("score") or 0.0)
        return {
            "score": max(0.0, min(1.0, score)),
            "ok": bool(data.get("ok", score >= 0.7)),
            "title": str(data.get("title") or "Helpful mini app")[:120],
            "brief": str(data.get("brief") or "")[:2000],
            "reason": str(data.get("reason") or ""),
            "raw": data,
        }
    except Exception as e:
        return {"score": 0.0, "ok": False, "title": "", "brief": "", "reason": f"score_failed: {e}"}
