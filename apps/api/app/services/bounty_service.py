"""Bounty lifecycle orchestration — real Grok, GitHub, X, evaluation only."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.crypto_tokens import decrypt_token
from app.models import (
    BaselineType,
    Bounty,
    BountyStatus,
    EventLog,
    Evaluation,
    EvalStatus,
    ProofOfCompletion,
    SettlementStatus,
    Submission,
    SubmissionSource,
    SubmissionStatus,
    User,
)
from app.schemas import BountyCreate, ExecutableContract
from app.services import xai_client
from app.services.github import resolve_github_url
from app.services.grok_baseline import PROMPT_VERSION, generate_optimize_baseline
from app.services.slug import public_slug
from app.services.x_client import create_post, extract_github_urls, post_url


async def log_event(
    db: AsyncSession,
    *,
    event_type: str,
    bounty_id: Optional[UUID] = None,
    submission_id: Optional[UUID] = None,
    source: str = "system",
    payload: Optional[dict] = None,
) -> None:
    db.add(
        EventLog(
            bounty_id=bounty_id,
            submission_id=submission_id,
            event_type=event_type,
            source=source,
            payload=payload,
        )
    )


async def create_bounty(db: AsyncSession, user: User, body: BountyCreate) -> Bounty:
    mode = getattr(body, "mode", None) or "optimize"
    baseline_type = BaselineType.NONE
    if mode == "beat_grok":
        baseline_type = BaselineType.GROK_GENERATED
    elif mode == "product":
        baseline_type = BaselineType.GROK_GENERATED

    bounty = Bounty(
        creator_id=user.id,
        title=body.title,
        natural_language=body.natural_language,
        reward_amount=body.reward_amount,
        reward_currency=body.reward_currency,
        repository_url=body.repository_url,
        seed_repository_url=body.repository_url,
        baseline_ref=body.baseline_ref,
        mode=mode,
        baseline_type=baseline_type,
        status=BountyStatus.CONTRACT_PENDING,
        public_slug=public_slug(),
        settlement_status=SettlementStatus.AWAITING_PAYMENT_RAIL,
        settlement_note=(
            "X Money is not currently programmatically accessible through a public API "
            "available to this project. Settlement remains external."
        ),
    )
    db.add(bounty)
    await db.flush()
    await log_event(
        db,
        event_type="bounty_created",
        bounty_id=bounty.id,
        source="api",
        payload={"title": body.title, "mode": mode, "baseline_type": baseline_type.value},
    )
    await db.commit()
    await db.refresh(bounty)
    return bounty


async def compile_contract(db: AsyncSession, bounty: Bounty) -> Bounty:
    contract = await xai_client.structured_contract(
        natural_language=bounty.natural_language,
        repository_url=bounty.repository_url,
        baseline_ref=bounty.baseline_ref,
        title=bounty.title,
        reward_amount=bounty.reward_amount,
        reward_currency=bounty.reward_currency,
    )
    # Prefer demo-bounty sensible defaults if repo looks like ranklab
    contract_dict = contract.model_dump()
    if "ranklab" in bounty.repository_url or "demo-bounty" in bounty.repository_url:
        contract_dict = _demo_contract_overlay(contract_dict, bounty)

    bounty.contract_json = contract_dict
    bounty.status = BountyStatus.READY
    await log_event(
        db,
        event_type="contract_compiled",
        bounty_id=bounty.id,
        source="grok",
        payload={"summary": contract_dict.get("summary")},
    )
    await db.commit()
    await db.refresh(bounty)
    return bounty


def _demo_contract_overlay(contract: dict[str, Any], bounty: Bounty) -> dict[str, Any]:
    """
    Deterministic runnable contracts for demo seeds.
    Still data-driven; does not hardcode winners.
    """
    settings = get_settings()
    repo = bounty.repository_url or ""
    root = Path(settings.workspaces_dir).resolve().parent
    if "demo-search" in repo or "searchlab" in repo:
        for candidate in (
            Path(os.environ["DEMO_SEARCH_PATH"]) / "eval_assets" if os.environ.get("DEMO_SEARCH_PATH") else None,
            Path("/app/demo-search/eval_assets"),
            root / "demo-search" / "eval_assets",
            Path(repo) / "eval_assets",
            Path(repo.replace("file://", "")) / "eval_assets",
        ):
            if candidate and candidate.exists():
                eval_assets = str(candidate.resolve())
                break
        else:
            eval_assets = str((root / "demo-search" / "eval_assets").resolve())
        contract["repository_url"] = bounty.repository_url
        contract["baseline_ref"] = bounty.baseline_ref
        contract["summary"] = contract.get("summary") or (
            "Beat Grok on a multi-objective search ranker: maximize NDCG@10 + MRR while "
            "keeping p95 latency low. Composite score is the sole ranking metric."
        )
        contract["target_description"] = (
            "Implement searchlab.ranker.rank(query, documents) -> list[doc_id] ordered best-first. "
            "Corpus documents have title, body, tags. Optimize quality vs latency tradeoff."
        )
        contract["build_command"] = "python3 -m pip install pytest -q || true"
        contract["visible_tests"] = [
            {
                "name": "visible_api_and_ordering",
                "command": "PYTHONPATH=. python3 -m pytest -q tests/visible",
                "hidden": False,
            }
        ]
        contract["hidden_tests"] = [
            {
                "name": "hidden_ranking_quality",
                "command": f"PYTHONPATH=. python3 -m pytest -q {eval_assets}/hidden",
                "hidden": True,
            }
        ]
        contract["benchmark"] = {
            "name": "composite_ranking_score",
            "command": "PYTHONPATH=. python3 bench/bench.py --json",
            "metric_key": "composite_score",
            "higher_is_better": True,
            "formula": "100*(0.7*NDCG@10 + 0.3*MRR) - 5.0*log10(1+p95_ms)",
            "reported_metrics": ["composite_score", "ndcg_at_10", "mrr", "p95_ms", "mean_ms"],
            "min_improvement_pct": 0.5,
            "min_improvement_over_grok_pct": 0.3,
            "warmup_runs": 1,
            "measured_runs": 5,
        }
        contract["integrity"] = {
            "protected_paths": ["eval/", "eval_assets/", "tests/hidden"],
            "forbid_env_checks": True,
            "forbid_benchmark_hardcoding": True,
            "require_semantic_equivalence": True,
        }
        contract["acceptance_criteria"] = [
            "All visible API/ordering tests pass",
            "Hidden ranking quality: avg NDCG@10 ≥ 0.65 on holdout queries + top-1 relevant",
            "Primary metric composite_score = 100*(0.7*NDCG@10 + 0.3*MRR) - 5.0*log10(1+p95_ms) (higher better)",
            "Beat frozen Grok Baseline V0 composite by ≥0.3% (same sandbox pipeline)",
            "No integrity violations: env probes, hardcoded public QRELS, protected-path edits",
            "Improvement must reproduce in a fresh sandbox clone",
        ]
        contract["evaluation_plan"] = [
            "Clone seed + candidate at pinned SHAs into isolated workspaces",
            "Run visible pytest suite on candidate",
            "Mount protected eval_assets and run hidden graded-relevance tests",
            "Benchmark seed + candidate: emit NDCG@10, MRR, p95_ms, composite_score JSON",
            "Static integrity scan for gaming patterns",
            "Fresh-sandbox reproduction of candidate benchmark",
            "Build eval vector; compare challengers vs frozen Grok vector",
        ]
        return contract

    # Default: RankLab latency bounty
    eval_assets = str((root / "demo-bounty" / "eval_assets").resolve())
    contract["repository_url"] = bounty.repository_url
    contract["baseline_ref"] = bounty.baseline_ref
    contract["build_command"] = "python3 -m pip install pytest -q || true"
    contract["visible_tests"] = [
        {
            "name": "visible",
            "command": "PYTHONPATH=. python3 -m pytest -q tests/visible",
            "hidden": False,
        }
    ]
    contract["hidden_tests"] = [
        {
            "name": "semantic_hidden",
            "command": f"PYTHONPATH=. python3 -m pytest -q {eval_assets}/hidden",
            "hidden": True,
        }
    ]
    contract["benchmark"] = {
        "name": "p95_latency",
        "command": "PYTHONPATH=. python3 bench/bench.py --json",
        "metric_key": "p95_ms",
        "higher_is_better": False,
        "min_improvement_pct": 25.0,
        "min_improvement_over_grok_pct": 5.0,
        "warmup_runs": 1,
        "measured_runs": 7,
    }
    contract["integrity"] = {
        "protected_paths": ["eval/", "eval_assets/", "tests/hidden"],
        "forbid_env_checks": True,
        "forbid_benchmark_hardcoding": True,
        "require_semantic_equivalence": True,
    }
    if not contract.get("acceptance_criteria"):
        contract["acceptance_criteria"] = [
            "All visible tests pass",
            "All hidden semantic tests pass",
            "p95 latency improved by at least 25% vs baseline",
            "Improvement reproduces in a clean sandbox",
            "No integrity violations (env detection, hardcoding, protected path edits)",
        ]
    return contract


async def approve_contract(
    db: AsyncSession,
    bounty: Bounty,
    *,
    approved: bool,
    edits: Optional[dict] = None,
) -> Bounty:
    if edits and bounty.contract_json:
        merged = dict(bounty.contract_json)
        merged.update(edits)
        bounty.contract_json = merged
    bounty.contract_approved = approved
    if approved:
        bounty.status = BountyStatus.BASELINE_VALIDATING
    await log_event(
        db,
        event_type="contract_approved" if approved else "contract_rejected",
        bounty_id=bounty.id,
        source="creator",
    )
    await db.commit()
    await db.refresh(bounty)
    return bounty


async def validate_baseline(db: AsyncSession, bounty: Bounty) -> Bounty:
    """Resolve baseline SHA and optionally run baseline bench (real)."""
    from app.services.evaluator import clone_commit, parse_bench_json, run_local_command

    resolved = await resolve_github_url(bounty.repository_url, default_ref=bounty.baseline_ref)
    # Local path support for demo: file:// or local path
    bounty.baseline_commit_sha = resolved.commit_sha
    settings = get_settings()
    ws = Path(settings.workspaces_dir) / str(bounty.id) / "baseline_validation"
    try:
        clone_commit(resolved.clone_url, resolved.commit_sha, ws)
    except Exception:
        # Allow local demo repo path
        local = Path(bounty.repository_url.replace("file://", ""))
        if local.exists():
            import shutil

            if ws.exists():
                shutil.rmtree(ws)
            shutil.copytree(
                local,
                ws,
                ignore=shutil.ignore_patterns(".git", "variants", "workspaces", "__pycache__"),
            )
            # create a synthetic sha from content
            bounty.baseline_commit_sha = bounty.baseline_commit_sha or "local-baseline"
        else:
            raise

    contract = bounty.contract_json or {}
    build = contract.get("build_command") or "pip install -e '.[dev]' -q"
    run_local_command(build, cwd=ws, timeout=300)
    bench_cmd = (contract.get("benchmark") or {}).get("command") or "python bench/bench.py --json"
    r = run_local_command(bench_cmd, cwd=ws, timeout=180)
    metrics = {}
    try:
        metrics = parse_bench_json(r.stdout)
    except Exception as e:
        metrics = {"error": str(e), "stdout": r.stdout[-2000:], "exit": r.exit_code}
    bounty.baseline_metrics = metrics
    bounty.status = BountyStatus.READY
    await log_event(
        db,
        event_type="baseline_validated",
        bounty_id=bounty.id,
        source="evaluator",
        payload=metrics,
    )
    await db.commit()
    await db.refresh(bounty)
    return bounty


async def generate_and_freeze_grok_baseline(db: AsyncSession, bounty: Bounty) -> Bounty:
    """
    Grok Build creates a real repo → first-class submission → same evaluator → freeze.
    """
    from app.services.eval_pipeline import run_evaluation_job

    settings = get_settings()
    bounty.status = BountyStatus.BASELINE_GENERATING
    bounty.baseline_type = BaselineType.GROK_GENERATED
    await db.commit()

    seed = Path((bounty.seed_repository_url or bounty.repository_url).replace("file://", ""))
    if not seed.exists():
        raise FileNotFoundError(f"Seed repository not found: {seed}")

    out_root = Path(settings.workspaces_dir) / str(bounty.id) / "grok_generation"
    # Prefer CLI locally; on Fly/containers CLI is usually absent → xAI API first.
    prefer_cli = not Path("/app/demo-search").exists()
    gen = await generate_optimize_baseline(
        seed_path=seed,
        out_root=out_root,
        natural_language=bounty.natural_language,
        prefer_cli=prefer_cli,
    )
    if not gen.ok:
        bounty.status = BountyStatus.FAILED
        await log_event(
            db,
            event_type="grok_baseline_failed",
            bounty_id=bounty.id,
            source="grok_build",
            payload={"error": gen.error, "meta": gen.generation_metadata},
        )
        await db.commit()
        raise RuntimeError(gen.error or "Grok baseline generation failed")

    sub = Submission(
        bounty_id=bounty.id,
        source_type=SubmissionSource.GROK_BASELINE,
        submitter_x_username="grok",
        github_url=gen.repo_path,
        commit_sha=gen.commit_sha,
        status=SubmissionStatus.QUEUED,
        generation_metadata=gen.generation_metadata,
        x_reply_text=f"Grok Baseline V0 @ {gen.commit_sha[:12]}",
    )
    db.add(sub)
    await db.flush()
    db.add(Evaluation(submission_id=sub.id, status=EvalStatus.PENDING))

    bounty.baseline_generation_run_id = gen.run_id
    bounty.baseline_model = gen.model
    bounty.baseline_prompt_version = PROMPT_VERSION
    bounty.baseline_generated_at = datetime.now(timezone.utc)
    bounty.baseline_commit_sha = gen.commit_sha  # seed SHA may differ; store gen commit here too
    # Keep seed for evaluation absolute baseline; repository_url stays seed for demo
    bounty.seed_repository_url = bounty.seed_repository_url or bounty.repository_url
    await log_event(
        db,
        event_type="grok_baseline_generated",
        bounty_id=bounty.id,
        submission_id=sub.id,
        source="grok_build",
        payload={
            "commit_sha": gen.commit_sha,
            "repo_path": gen.repo_path,
            "method": gen.method,
            "run_id": gen.run_id,
            "model": gen.model,
        },
    )
    await db.commit()

    # Same evaluation pipeline as humans
    evaluation = await run_evaluation_job(db, sub.id)

    bounty = await db.get(Bounty, bounty.id)
    assert bounty
    bounty.baseline_submission_id = sub.id
    bounty.baseline_evaluation_id = evaluation.id
    bounty.baseline_eval_vector = evaluation.eval_vector
    bounty.champion_submission_id = sub.id if sub.status == SubmissionStatus.COMPLETED else None
    bounty.status = BountyStatus.READY
    await log_event(
        db,
        event_type="grok_baseline_frozen",
        bounty_id=bounty.id,
        submission_id=sub.id,
        source="system",
        payload={
            "commit_sha": gen.commit_sha,
            "eval_vector": evaluation.eval_vector,
            "status": sub.status.value,
        },
    )
    await db.commit()
    await db.refresh(bounty)
    return bounty


async def publish_bounty(db: AsyncSession, bounty: Bounty, user: User) -> Bounty:
    if not bounty.contract_approved:
        raise ValueError("Contract must be approved before publish")
    if bounty.baseline_type == BaselineType.GROK_GENERATED and not bounty.baseline_submission_id:
        raise ValueError("Grok baseline must be generated and frozen before publish")
    if not user.oauth:
        # reload oauth
        result = await db.execute(select(User).options(selectinload(User.oauth)).where(User.id == user.id))
        user = result.scalar_one()
    if not user.oauth:
        raise RuntimeError("User has no X OAuth tokens. Sign in with X first.")

    access = decrypt_token(user.oauth.access_token_enc)
    settings = get_settings()
    link = f"{settings.app_base_url}/b/{bounty.public_slug}"
    if bounty.baseline_type == BaselineType.GROK_GENERATED:
        text = (
            f"${bounty.reward_amount:g} ProofPay — Beat Grok\n"
            f"{bounty.title}\n"
            f"Grok V0: {bounty.baseline_commit_sha[:10] if bounty.baseline_commit_sha else 'frozen'}\n"
            f"Submit GitHub below. Contract: {link}"
        )[:280]
    else:
        text = (
            f"${bounty.reward_amount:g} {bounty.reward_currency} ProofPay bounty:\n\n"
            f"{bounty.title}\n\n"
            f"{bounty.natural_language[:400]}\n\n"
            f"Submit your GitHub branch/PR in the replies.\n"
            f"Full executable contract: {link}"
        )
        if len(text) > 280:
            text = (
                f"${bounty.reward_amount:g} ProofPay bounty: {bounty.title}\n\n"
                f"Submit GitHub PR/branch in replies.\n"
                f"Contract: {link}"
            )[:280]

    resp = await create_post(text, access_token=access)
    data = resp.get("data") or resp
    post_id = str(data.get("id"))
    bounty.x_post_id = post_id
    bounty.conversation_id = post_id  # root conversation id equals post id for original posts
    bounty.x_post_url = post_url(user.x_username, post_id)
    bounty.status = BountyStatus.PUBLISHED
    bounty.published_at = datetime.now(timezone.utc)
    await log_event(
        db,
        event_type="bounty_published",
        bounty_id=bounty.id,
        source="x",
        payload={"post_id": post_id, "url": bounty.x_post_url},
    )
    await db.commit()
    await db.refresh(bounty)
    return bounty


async def ingest_reply_submission(
    db: AsyncSession,
    *,
    bounty: Bounty,
    reply_id: str,
    reply_text: str,
    author_id: Optional[str],
    author_username: Optional[str],
) -> Optional[Submission]:
    urls = extract_github_urls(reply_text)
    if not urls:
        await log_event(
            db,
            event_type="reply_without_github",
            bounty_id=bounty.id,
            source="x",
            payload={"reply_id": reply_id, "text": reply_text[:500]},
        )
        await db.commit()
        return None

    # dedupe by reply id
    existing = await db.execute(select(Submission).where(Submission.x_reply_id == reply_id))
    if existing.scalar_one_or_none():
        return existing.scalar_one_or_none()

    github_url = urls[0]
    sub = Submission(
        bounty_id=bounty.id,
        source_type=SubmissionSource.HUMAN,
        submitter_x_user_id=author_id,
        submitter_x_username=author_username,
        x_reply_id=reply_id,
        x_reply_text=reply_text,
        github_url=github_url,
        status=SubmissionStatus.RESOLVING,
    )

    db.add(sub)
    await db.flush()
    await log_event(
        db,
        event_type="submission_detected",
        bounty_id=bounty.id,
        submission_id=sub.id,
        source="x",
        payload={"github_url": github_url, "username": author_username},
    )

    try:
        resolved = await resolve_github_url(github_url)
        sub.github_owner = resolved.owner
        sub.github_repo = resolved.repo
        sub.github_ref = resolved.ref
        sub.pr_number = resolved.pr_number
        sub.commit_sha = resolved.commit_sha
        sub.status = SubmissionStatus.QUEUED
    except Exception as e:
        # Local path / demo variants
        if github_url.startswith("file://") or github_url.startswith("/"):
            sub.commit_sha = f"local-{secrets.token_hex(8)}"
            sub.status = SubmissionStatus.QUEUED
            sub.github_ref = "local"
        else:
            sub.status = SubmissionStatus.ERROR
            await log_event(
                db,
                event_type="submission_resolve_failed",
                bounty_id=bounty.id,
                submission_id=sub.id,
                source="github",
                payload={"error": str(e)},
            )

    db.add(Evaluation(submission_id=sub.id, status=EvalStatus.PENDING))
    bounty.status = BountyStatus.EVALUATING
    await db.commit()
    await db.refresh(sub)
    return sub


async def get_bounty(db: AsyncSession, bounty_id: UUID) -> Optional[Bounty]:
    r = await db.execute(
        select(Bounty)
        .options(selectinload(Bounty.creator), selectinload(Bounty.submissions))
        .where(Bounty.id == bounty_id)
    )
    return r.scalar_one_or_none()


async def get_bounty_by_slug(db: AsyncSession, slug: str) -> Optional[Bounty]:
    r = await db.execute(
        select(Bounty)
        .options(selectinload(Bounty.creator), selectinload(Bounty.submissions))
        .where(Bounty.public_slug == slug)
    )
    return r.scalar_one_or_none()
