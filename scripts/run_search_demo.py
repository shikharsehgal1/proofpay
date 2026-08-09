#!/usr/bin/env python3
"""
Run SearchLab Beat-Grok demo with 3 agent bots (real evaluations).

Agents:
  alice   — TF-IDF quality ranker
  bob     — ignores query (fails hidden gates)
  charlie — hardcodes public bench queries (integrity fail)

Usage (API running on :8000):
  cd apps/api && source .venv/bin/activate
  python ../../scripts/run_search_demo.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import SessionLocal, engine, Base
from app.db_migrate import ensure_schema
from app.models import (
    User,
    Bounty,
    BountyStatus,
    Submission,
    SubmissionSource,
    SubmissionStatus,
    Evaluation,
    EvalStatus,
)
from app.schemas import BountyCreate
from app.services.bounty_service import (
    create_bounty,
    approve_contract,
    generate_and_freeze_grok_baseline,
    _demo_contract_overlay,
)
from app.services.eval_pipeline import run_evaluation_job


SEED = ROOT / "demo-search"
AGENTS = [
    ("alice", SEED / "variants" / "alice"),       # BM25 field-weighted — legitimate challenger
    ("bob", SEED / "variants" / "bob"),           # ignores query — fails quality gates
    ("charlie", SEED / "variants" / "charlie"),   # hardcodes public QRELS + env probe — integrity fail
]


async def main() -> None:
    await ensure_schema(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        u = (await db.execute(select(User).where(User.x_username == "demo_creator"))).scalar_one_or_none()
        if not u:
            # prefer real OAuth user if present
            u = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().first()
        if not u:
            u = User(x_user_id="demo-1", x_username="demo_creator", display_name="Demo Creator")
            db.add(u)
            await db.commit()
            await db.refresh(u)

        body = BountyCreate(
            title="Beat Grok: Complex Multi-Metric Search Ranking",
            natural_language=(
                "Implement a high-quality production search ranker in searchlab.ranker.rank(query, documents) -> list[doc_ids]. "
                "Maximize composite_score = 100*(0.7*NDCG@10 + 0.3*MRR) - 5.0*log10(1 + p95_latency_ms). "
                "Corpus has rich metadata (title, body, tags, date). Hidden test set has different query distribution. "
                "Must pass visible tests, hidden quality gates, integrity (no env detection, no hardcoding public queries, "
                "no tampering with eval/). Real sandbox execution with Docker isolation where available. "
                "Tradeoff quality vs low latency is the core challenge — beat Grok's baseline on the full eval vector."
            ),
            reward_amount=100,
            reward_currency="USD",
            repository_url=str(SEED),
            baseline_ref="main",
            mode="beat_grok",
        )
        bounty = await create_bounty(db, u, body)
        bounty.contract_json = _demo_contract_overlay(
            {
                "summary": "Multi-metric search ranking",
                "target_description": "searchlab.ranker.rank",
                "repository_url": str(SEED),
                "baseline_ref": "main",
                "acceptance_criteria": [],
                "evaluation_plan": [],
            },
            bounty,
        )
        await db.commit()
        bounty = await approve_contract(db, bounty, approved=True)

        print("Generating Grok Baseline V0 (real)...")
        bounty = await generate_and_freeze_grok_baseline(db, bounty)
        print(
            "Grok V0 commit:",
            bounty.baseline_commit_sha,
            "vector:",
            (bounty.baseline_eval_vector or {}).get("performance"),
        )

        for name, path in AGENTS:
            print(f"\n=== Agent @{name} submitting {path} ===")
            sub = Submission(
                bounty_id=bounty.id,
                source_type=SubmissionSource.HUMAN,
                submitter_x_username=name,
                github_url=str(path),
                commit_sha=f"agent-{name}",
                status=SubmissionStatus.QUEUED,
                x_reply_text=f"@{name} agent submission — complex ranking demo: {path.name}",
            )
            db.add(sub)
            await db.flush()
            db.add(Evaluation(submission_id=sub.id, status=EvalStatus.PENDING))
            await db.commit()
            ev = await run_evaluation_job(db, sub.id)
            await db.refresh(sub)
            perf = (ev.eval_vector or {}).get("performance") if ev.eval_vector else {}
            print(
                {
                    "status": sub.status.value,
                    "beats_grok": sub.beats_grok,
                    "verdict": (sub.vs_grok_delta or {}).get("verdict"),
                    "reason": (sub.vs_grok_delta or {}).get("reason"),
                    "composite": perf.get("composite_score") if perf else None,
                    "ndcg": perf.get("ndcg_at_10") if perf else None,
                    "mrr": perf.get("mrr") if perf else None,
                    "p95": perf.get("latency_ms") if perf else None,
                    "error": ev.error_message,
                }
            )

        r = await db.execute(
            select(Submission)
            .options(selectinload(Submission.evaluation))
            .where(Submission.bounty_id == bounty.id)
        )
        print("\n=== LEADERBOARD ===")
        for s in r.scalars().all():
            cm = (s.evaluation.raw_results or {}).get("candidate_metrics") if s.evaluation else {}
            print(
                f"{s.source_type.value:14} @{s.submitter_x_username:8} "
                f"{s.status.value:12} beats_grok={s.beats_grok} rank={s.rank} "
                f"composite={cm.get('composite_score')} ndcg={cm.get('ndcg_at_10')} "
                f"p95_ms={cm.get('p95_ms')} imp={s.evaluation.improvement_pct if s.evaluation else None}%"
            )
        print("\nBOUNTY_ID", bounty.id)
        print("PUBLIC_SLUG", bounty.public_slug)
        print(f"Contract / demo page: https://proofpay-web.fly.dev/b/{bounty.public_slug}")
        print("   (or run locally: http://localhost:3000/b/" + bounty.public_slug + ")")


if __name__ == "__main__":
    asyncio.run(main())
