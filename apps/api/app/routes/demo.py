"""Demo seeding endpoints — real evaluations, no fake scores."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.models import (
    Evaluation,
    EvalStatus,
    Submission,
    SubmissionSource,
    SubmissionStatus,
    User,
)
from app.schemas import BountyCreate, BountyOut
from app.services.bounty_service import (
    approve_contract,
    create_bounty,
    generate_and_freeze_grok_baseline,
    _demo_contract_overlay,
)
from app.services.eval_pipeline import run_evaluation_job

router = APIRouter(prefix="/demo", tags=["demo"])


def _seed_path() -> Path:
    candidates: list[Path] = []
    if os.environ.get("DEMO_SEARCH_PATH"):
        candidates.append(Path(os.environ["DEMO_SEARCH_PATH"]))
    candidates.append(Path("/app/demo-search"))
    candidates.append(Path("demo-search"))
    # Local monorepo layout (only if deep enough)
    try:
        candidates.append(Path(__file__).resolve().parents[4] / "demo-search")
    except IndexError:
        pass
    try:
        candidates.append(Path(__file__).resolve().parents[3] / "demo-search")
    except IndexError:
        pass
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"demo-search seed not found; tried {[str(c) for c in candidates]}")


@router.post("/seed-search-bounty")
async def seed_search_bounty(
    db: AsyncSession = Depends(get_db),
    run_agents: bool = True,
    generate_grok: bool = True,
):
    """
    Create the complex multi-metric SearchLab Beat-Grok bounty on this API instance
    (works on Fly). Optionally freeze Grok baseline and evaluate 3 agent bots.

    Agents:
      alice   — BM25 field-weighted (strong legitimate challenger)
      bob     — ignores query (fails quality gates)
      charlie — hardcodes public QRELS + env probe (fails integrity / hidden)
    """
    settings = get_settings()
    try:
        seed = _seed_path()
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))

    u = (await db.execute(select(User).where(User.x_username == "demo_creator"))).scalar_one_or_none()
    if not u:
        u = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().first()
    if not u:
        u = User(x_user_id="demo-fly-1", x_username="demo_creator", display_name="Demo Creator")
        db.add(u)
        await db.commit()
        await db.refresh(u)

    body = BountyCreate(
        title="Beat Grok: Complex Multi-Metric Search Ranking",
        natural_language=(
            "Implement a high-quality production search ranker in "
            "searchlab.ranker.rank(query, documents) -> list[doc_ids]. "
            "Maximize composite_score = 100*(0.7*NDCG@10 + 0.3*MRR) - 5.0*log10(1 + p95_latency_ms). "
            "Corpus has rich metadata (title, body, tags). Hidden test set has different query "
            "distribution. Must pass visible tests, hidden quality gates, and integrity checks "
            "(no env detection, no hardcoding public queries). Tradeoff quality vs latency is the "
            "core challenge — beat Grok's frozen baseline on the full eval vector."
        ),
        reward_amount=100,
        reward_currency="USD",
        repository_url=str(seed),
        baseline_ref="main",
        mode="beat_grok",
    )
    bounty = await create_bounty(db, u, body)
    bounty.contract_json = _demo_contract_overlay(
        {
            "summary": "Multi-metric search ranking (NDCG + MRR + latency)",
            "target_description": "searchlab.ranker.rank",
            "repository_url": str(seed),
            "baseline_ref": "main",
            "acceptance_criteria": [],
            "evaluation_plan": [],
        },
        bounty,
    )
    await db.commit()
    bounty = await approve_contract(db, bounty, approved=True)

    results: dict = {
        "bounty_id": str(bounty.id),
        "public_slug": bounty.public_slug,
        "contract_url": f"{settings.app_base_url}/b/{bounty.public_slug}",
        "agents": [],
        "grok": None,
    }

    if generate_grok:
        try:
            bounty = await generate_and_freeze_grok_baseline(db, bounty)
            results["grok"] = {
                "commit": bounty.baseline_commit_sha,
                "eval_vector": bounty.baseline_eval_vector,
                "status": "frozen",
            }
        except Exception as e:
            results["grok"] = {"status": "failed", "error": str(e)}

    if run_agents:
        agents = [
            ("alice", seed / "variants" / "alice"),
            ("bob", seed / "variants" / "bob"),
            ("charlie", seed / "variants" / "charlie"),
        ]
        for name, path in agents:
            if not path.exists():
                results["agents"].append({"name": name, "error": f"missing {path}"})
                continue
            sub = Submission(
                bounty_id=bounty.id,
                source_type=SubmissionSource.HUMAN,
                submitter_x_username=name,
                github_url=str(path),
                commit_sha=f"agent-{name}",
                status=SubmissionStatus.QUEUED,
                x_reply_text=f"@{name} agent bot submission for multi-metric ranking demo",
            )
            db.add(sub)
            await db.flush()
            db.add(Evaluation(submission_id=sub.id, status=EvalStatus.PENDING))
            await db.commit()
            try:
                ev = await run_evaluation_job(db, sub.id)
                await db.refresh(sub)
                cm = (ev.raw_results or {}).get("candidate_metrics") or {}
                results["agents"].append(
                    {
                        "name": name,
                        "status": sub.status.value,
                        "beats_grok": sub.beats_grok,
                        "verdict": (sub.vs_grok_delta or {}).get("verdict"),
                        "composite": cm.get("composite_score"),
                        "ndcg": cm.get("ndcg_at_10"),
                        "mrr": cm.get("mrr"),
                        "p95_ms": cm.get("p95_ms"),
                        "error": ev.error_message,
                    }
                )
            except Exception as e:
                results["agents"].append({"name": name, "error": str(e)})

    # refresh leaderboard snapshot
    r = await db.execute(
        select(Submission)
        .options(selectinload(Submission.evaluation))
        .where(Submission.bounty_id == bounty.id)
    )
    results["leaderboard"] = [
        {
            "source": s.source_type.value if s.source_type else None,
            "user": s.submitter_x_username,
            "status": s.status.value,
            "rank": s.rank,
            "beats_grok": s.beats_grok,
            "composite": ((s.evaluation.raw_results or {}).get("candidate_metrics") or {}).get(
                "composite_score"
            )
            if s.evaluation
            else None,
        }
        for s in r.scalars().all()
    ]
    results["contract_url"] = f"{settings.app_base_url}/b/{bounty.public_slug}"
    return results
