"""Proof of Completion + winner announcement. Settlement stops at READY_FOR_SETTLEMENT without X Money API."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.crypto_tokens import decrypt_token
from app.models import (
    Bounty,
    BountyStatus,
    ProofOfCompletion,
    SettlementStatus,
    Submission,
    User,
)
from app.services.bounty_service import log_event
from app.services.x_client import create_post, post_url, upload_media_simple
from app.services.winner_card import render_winner_card


async def create_proof_and_announce(
    db: AsyncSession,
    *,
    bounty: Bounty,
    submission: Submission,
    creator: User,
    post_announcement: bool = True,
) -> ProofOfCompletion:
    # Clear previous winner flags
    for s in bounty.submissions or []:
        s.is_winner = False
    submission.is_winner = True
    bounty.winner_submission_id = submission.id
    bounty.status = BountyStatus.VERIFIED
    bounty.settlement_status = SettlementStatus.AWAITING_PAYMENT_RAIL
    bounty.settlement_note = (
        "X Money is not currently programmatically accessible through a public API "
        "available to this project. State: VERIFIED — READY FOR EXTERNAL SETTLEMENT."
    )

    ev = submission.evaluation
    proof_json: dict[str, Any] = {
        "bounty_id": str(bounty.id),
        "bounty_title": bounty.title,
        "reward": {"amount": bounty.reward_amount, "currency": bounty.reward_currency},
        "winner": {
            "x_username": submission.submitter_x_username,
            "github_url": submission.github_url,
            "commit_sha": submission.commit_sha,
        },
        "metrics": {
            "improvement_pct": ev.improvement_pct if ev else None,
            "visible_tests": f"{ev.visible_tests_passed}/{ev.visible_tests_total}" if ev else None,
            "hidden_tests": f"{ev.hidden_tests_passed}/{ev.hidden_tests_total}" if ev else None,
            "baseline_latency_ms": ev.baseline_latency_ms if ev else None,
            "candidate_latency_ms": ev.candidate_latency_ms if ev else None,
            "reproduction_improvement_pct": ev.reproduction_improvement_pct if ev else None,
            "integrity_ok": ev.integrity_ok if ev else None,
        },
        "x_bounty_post_id": bounty.x_post_id,
        "settlement": {
            "status": bounty.settlement_status.value,
            "note": bounty.settlement_note,
            "x_money_api": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "proofpay-real-pipeline",
    }

    settings = get_settings()
    path = f"/proofs/{bounty.public_slug}"
    card_path = None
    try:
        card_path = render_winner_card(
            username=submission.submitter_x_username or "winner",
            improvement_pct=ev.improvement_pct if ev else 0,
            visible=f"{ev.visible_tests_passed}/{ev.visible_tests_total}" if ev else "n/a",
            hidden=f"{ev.hidden_tests_passed}/{ev.hidden_tests_total}" if ev else "n/a",
            bounty_title=bounty.title,
            out_dir=Path(settings.artifacts_dir) / str(bounty.id),
        )
    except Exception:
        card_path = None

    announcement_id = None
    if post_announcement and creator.oauth and bounty.x_post_id:
        try:
            access = decrypt_token(creator.oauth.access_token_enc)
            media_ids = None
            if card_path and Path(card_path).exists():
                try:
                    media_ids = [
                        await upload_media_simple(
                            Path(card_path).read_bytes(),
                            access_token=access,
                        )
                    ]
                except Exception:
                    media_ids = None
            proof_link = f"{settings.app_base_url}{path}"
            imp = ev.improvement_pct if ev else 0
            text = (
                f"🏆 @{submission.submitter_x_username or 'winner'} completed the "
                f"${bounty.reward_amount:g} ProofPay bounty.\n\n"
                f"Verified improvement: {imp:.1f}%\n"
                f"Visible tests: {proof_json['metrics']['visible_tests']}\n"
                f"Hidden tests: {proof_json['metrics']['hidden_tests']}\n"
                f"Reproduced: {(ev.reproduction_improvement_pct or 0):.1f}%\n\n"
                f"Proof: {proof_link}\n"
                f"Settlement: awaiting external rail (no public X Money API)"
            )[:280]
            resp = await create_post(
                text,
                access_token=access,
                in_reply_to=bounty.x_post_id,
                media_ids=media_ids,
            )
            announcement_id = str((resp.get("data") or resp).get("id"))
        except Exception as e:
            await log_event(
                db,
                event_type="winner_announce_failed",
                bounty_id=bounty.id,
                submission_id=submission.id,
                source="x",
                payload={"error": str(e)},
            )

    bounty.status = BountyStatus.READY_FOR_SETTLEMENT
    proof = ProofOfCompletion(
        bounty_id=bounty.id,
        submission_id=submission.id,
        proof_json=proof_json,
        public_url_path=path,
        winner_card_path=card_path,
        x_announcement_post_id=announcement_id,
    )
    db.add(proof)
    await log_event(
        db,
        event_type="winner_selected",
        bounty_id=bounty.id,
        submission_id=submission.id,
        source="creator",
        payload={"announcement_id": announcement_id, "proof": proof_json["metrics"]},
    )
    await db.commit()
    await db.refresh(proof)
    return proof
