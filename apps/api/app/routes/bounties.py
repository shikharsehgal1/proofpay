from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth_session import get_current_user, get_optional_user
from app.db import SessionLocal, get_db
from app.models import (
    BaselineType,
    Bounty,
    BountyStatus,
    EventLog,
    ProofOfCompletion,
    Submission,
    SubmissionSource,
    User,
)
from app.schemas import (
    BeatGrokVerdict,
    BountyCreate,
    BountyOut,
    ContractApprove,
    EventOut,
    ProofOut,
    SelectWinner,
    SubmissionCreateManual,
    SubmissionOut,
)
from app.services import bounty_service
from app.services.eval_pipeline import run_evaluation_job
from app.services.proof import create_proof_and_announce

router = APIRouter(prefix="/bounties", tags=["bounties"])


def _bounty_out(b: Bounty) -> BountyOut:
    return BountyOut.model_validate(b)


@router.post("", response_model=BountyOut)
async def create_bounty(
    body: BountyCreate,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bounty = await bounty_service.create_bounty(db, user, body)

    async def _compile(bid: UUID):
        async with SessionLocal() as session:
            b = await session.get(Bounty, bid)
            if not b:
                return
            try:
                await bounty_service.compile_contract(session, b)
            except Exception as e:
                b.status = b.status  # noqa
                from app.models import BountyStatus

                b.status = BountyStatus.FAILED
                await bounty_service.log_event(
                    session,
                    event_type="contract_compile_failed",
                    bounty_id=b.id,
                    source="grok",
                    payload={"error": str(e)},
                )
                await session.commit()

    background.add_task(_compile, bounty.id)
    # also try sync if xai available for snappier demo — still real
    from app.config import get_settings

    if get_settings().xai_configured:
        try:
            bounty = await bounty_service.compile_contract(db, bounty)
        except Exception:
            pass
    await db.refresh(bounty)
    return _bounty_out(bounty)


@router.get("", response_model=List[BountyOut])
async def list_bounties(db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(Bounty).options(selectinload(Bounty.creator)).order_by(Bounty.created_at.desc()).limit(100)
    )
    return [_bounty_out(b) for b in r.scalars().all()]


@router.get("/slug/{slug}", response_model=BountyOut)
async def get_by_slug(slug: str, db: AsyncSession = Depends(get_db)):
    b = await bounty_service.get_bounty_by_slug(db, slug)
    if not b:
        raise HTTPException(404, "Bounty not found")
    return _bounty_out(b)


@router.get("/{bounty_id}", response_model=BountyOut)
async def get_bounty(bounty_id: UUID, db: AsyncSession = Depends(get_db)):
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b:
        raise HTTPException(404, "Bounty not found")
    return _bounty_out(b)


@router.post("/{bounty_id}/compile", response_model=BountyOut)
async def recompile(bounty_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b or b.creator_id != user.id:
        raise HTTPException(404, "Bounty not found")
    try:
        b = await bounty_service.compile_contract(db, b)
    except Exception as e:
        raise HTTPException(503, str(e)) from e
    return _bounty_out(b)


@router.post("/{bounty_id}/approve-contract", response_model=BountyOut)
async def approve(
    bounty_id: UUID,
    body: ContractApprove,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b or b.creator_id != user.id:
        raise HTTPException(404, "Bounty not found")
    b = await bounty_service.approve_contract(db, b, approved=body.approved, edits=body.edits)
    if body.approved:
        # Seed validation for absolute metrics (legacy + beat_grok)
        try:
            b = await bounty_service.validate_baseline(db, b)
        except Exception as e:
            await bounty_service.log_event(
                db,
                event_type="seed_validation_failed",
                bounty_id=b.id,
                source="evaluator",
                payload={"error": str(e)},
            )
            await db.commit()
    return _bounty_out(b)


@router.post("/{bounty_id}/generate-grok-baseline", response_model=BountyOut)
async def generate_grok_baseline(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Ask Grok Build to produce Baseline V0, evaluate it like any contestant, freeze it.
    """
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b or b.creator_id != user.id:
        raise HTTPException(404, "Bounty not found")
    if not b.contract_approved:
        raise HTTPException(400, "Approve the contract before generating Grok baseline")
    try:
        b = await bounty_service.generate_and_freeze_grok_baseline(db, b)
    except Exception as e:
        raise HTTPException(503, str(e)) from e
    return _bounty_out(b)


@router.get("/{bounty_id}/beat-grok", response_model=BeatGrokVerdict)
async def beat_grok_verdict(bounty_id: UUID, db: AsyncSession = Depends(get_db)):
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b:
        raise HTTPException(404, "Bounty not found")
    r = await db.execute(
        select(Submission)
        .options(selectinload(Submission.evaluation))
        .where(Submission.bounty_id == bounty_id)
        .order_by(Submission.created_at.asc())
    )
    subs = list(r.scalars().all())
    challengers = []
    any_beat = False
    best_human = None
    for s in subs:
        if s.source_type == SubmissionSource.GROK_BASELINE:
            continue
        row = {
            "id": str(s.id),
            "username": s.submitter_x_username,
            "status": s.status.value,
            "beats_grok": s.beats_grok,
            "vs_grok": s.vs_grok_delta,
            "latency_ms": s.evaluation.candidate_latency_ms if s.evaluation else None,
            "eval_vector": s.evaluation.eval_vector if s.evaluation else None,
        }
        challengers.append(row)
        if s.beats_grok:
            any_beat = True
            if best_human is None:
                best_human = s
            elif (
                s.evaluation
                and best_human.evaluation
                and (s.evaluation.candidate_latency_ms or 1e18)
                < (best_human.evaluation.candidate_latency_ms or 1e18)
            ):
                best_human = s

    if any_beat and best_human:
        verdict = "VERIFIED_IMPROVEMENT_OVER_GROK"
        champion = best_human.submitter_x_username or "human"
    else:
        verdict = "GROK_REMAINS_CHAMPION"
        champion = "grok"

    return BeatGrokVerdict(
        bounty_id=bounty_id,
        champion=champion,
        verdict=verdict,
        baseline_commit_sha=b.baseline_commit_sha,
        baseline_eval_vector=b.baseline_eval_vector,
        challengers=challengers,
    )


@router.post("/{bounty_id}/publish", response_model=BountyOut)
async def publish(
    bounty_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b or b.creator_id != user.id:
        raise HTTPException(404, "Bounty not found")
    try:
        b = await bounty_service.publish_bounty(db, b, user)
    except Exception as e:
        raise HTTPException(502, str(e)) from e
    return _bounty_out(b)


@router.get("/{bounty_id}/submissions", response_model=List[SubmissionOut])
async def list_submissions(bounty_id: UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(Submission)
        .options(selectinload(Submission.evaluation))
        .where(Submission.bounty_id == bounty_id)
        .order_by(Submission.created_at.asc())
    )
    return [SubmissionOut.model_validate(s) for s in r.scalars().all()]


@router.post("/{bounty_id}/submissions", response_model=SubmissionOut)
async def manual_submission(
    bounty_id: UUID,
    body: SubmissionCreateManual,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_optional_user),
):
    """
    Manual ingest for demo ops when reply is known, OR local file:// variants.
    Still uses the exact same evaluation pipeline — not a result shortcut.
    """
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b:
        raise HTTPException(404, "Bounty not found")
    import secrets

    reply_id = body.x_reply_id or f"manual-{secrets.token_hex(8)}"
    sub = await bounty_service.ingest_reply_submission(
        db,
        bounty=b,
        reply_id=reply_id,
        reply_text=body.x_reply_text or body.github_url,
        author_id=None,
        author_username=body.submitter_x_username,
    )
    if not sub:
        raise HTTPException(400, "No GitHub URL found")

    async def _eval(sid: UUID):
        async with SessionLocal() as session:
            await run_evaluation_job(session, sid)

    background.add_task(_eval, sub.id)
    r = await db.execute(
        select(Submission).options(selectinload(Submission.evaluation)).where(Submission.id == sub.id)
    )
    sub = r.scalar_one()
    return SubmissionOut.model_validate(sub)


@router.post("/{bounty_id}/submissions/{submission_id}/evaluate", response_model=SubmissionOut)
async def evaluate_now(
    bounty_id: UUID,
    submission_id: UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(Submission)
        .options(selectinload(Submission.evaluation))
        .where(Submission.id == submission_id, Submission.bounty_id == bounty_id)
    )
    sub = r.scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Submission not found")

    # Run inline for hackathon feedback (real eval can take a bit)
    await run_evaluation_job(db, submission_id)
    r = await db.execute(
        select(Submission).options(selectinload(Submission.evaluation)).where(Submission.id == submission_id)
    )
    return SubmissionOut.model_validate(r.scalar_one())


@router.post("/{bounty_id}/select-winner", response_model=ProofOut)
async def select_winner(
    bounty_id: UUID,
    body: SelectWinner,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    b = await bounty_service.get_bounty(db, bounty_id)
    if not b or b.creator_id != user.id:
        raise HTTPException(404, "Bounty not found")
    r = await db.execute(
        select(Submission)
        .options(selectinload(Submission.evaluation))
        .where(Submission.id == body.submission_id, Submission.bounty_id == bounty_id)
    )
    sub = r.scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Submission not found")
    proof = await create_proof_and_announce(
        db, bounty=b, submission=sub, creator=user, post_announcement=body.post_announcement
    )
    return ProofOut.model_validate(proof)


@router.get("/{bounty_id}/events", response_model=List[EventOut])
async def events(bounty_id: UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(
        select(EventLog).where(EventLog.bounty_id == bounty_id).order_by(EventLog.created_at.asc())
    )
    return [EventOut.model_validate(e) for e in r.scalars().all()]


@router.get("/{bounty_id}/proof", response_model=ProofOut)
async def get_proof(bounty_id: UUID, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ProofOfCompletion).where(ProofOfCompletion.bounty_id == bounty_id))
    p = r.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "No proof yet")
    return ProofOut.model_validate(p)
