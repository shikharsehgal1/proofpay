"""End-to-end evaluation job: real sandbox metrics + Grok investigation + ranking."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import (
    BaselineType,
    Bounty,
    BountyStatus,
    Evaluation,
    EvalStatus,
    Submission,
    SubmissionSource,
    SubmissionStatus,
)
from app.services.bounty_service import log_event
from app.services.evaluator import evaluate_submission
from app.services.github import resolve_github_url
from app.services.grok_baseline import build_eval_vector, compare_to_grok
from app.services.investigator import investigate_submission


async def run_evaluation_job(db: AsyncSession, submission_id: UUID) -> Evaluation:
    result = await db.execute(
        select(Submission)
        .options(selectinload(Submission.evaluation), selectinload(Submission.bounty))
        .where(Submission.id == submission_id)
    )
    sub = result.scalar_one()
    bounty: Bounty = sub.bounty
    evaluation = sub.evaluation
    if evaluation is None:
        evaluation = Evaluation(submission_id=sub.id, status=EvalStatus.PENDING)
        db.add(evaluation)
        await db.flush()

    evaluation.status = EvalStatus.RUNNING
    evaluation.started_at = datetime.now(timezone.utc)
    sub.status = SubmissionStatus.EVALUATING
    await db.commit()

    settings = get_settings()
    contract = bounty.contract_json or {}
    eval_assets = Path("demo-bounty/eval_assets")
    if not eval_assets.exists():
        eval_assets = Path(__file__).resolve().parents[4] / "demo-bounty" / "eval_assets"

    # Seed repo for absolute metrics (not Grok's frozen tree).
    # Grok and humans both evaluate against the same seed when present.
    seed_url = bounty.seed_repository_url or bounty.repository_url
    try:
        base = await resolve_github_url(seed_url, default_ref=bounty.baseline_ref)
        baseline_clone = base.clone_url
        baseline_sha = bounty.baseline_commit_sha or base.commit_sha
    except Exception:
        baseline_clone = seed_url
        baseline_sha = bounty.baseline_commit_sha or "HEAD"

    try:
        cand = await resolve_github_url(sub.github_url)
        cand_clone = cand.clone_url
        cand_sha = sub.commit_sha or cand.commit_sha
        sub.commit_sha = cand_sha
    except Exception:
        # local file path variants for demo
        cand_clone = sub.github_url
        cand_sha = sub.commit_sha or "local"

    run = await evaluate_submission(
        bounty_id=str(bounty.id),
        submission_id=str(sub.id),
        clone_url=cand_clone if not cand_clone.startswith("/") else f"file://{cand_clone}",
        commit_sha=cand_sha,
        baseline_clone_url=baseline_clone if not str(baseline_clone).startswith("/") else f"file://{baseline_clone}",
        baseline_commit_sha=baseline_sha,
        contract=contract,
        eval_assets_dir=eval_assets if eval_assets.exists() else None,
    )

    # Handle local directories by copying if clone failed path
    if not run.ok and run.error and "git clone" in (run.error or ""):
        run = await _evaluate_local_paths(
            bounty=bounty,
            sub=sub,
            contract=contract,
            eval_assets=eval_assets,
        )

    m = run.metrics
    evaluation.visible_tests_passed = m.get("visible_tests_passed")
    evaluation.visible_tests_total = m.get("visible_tests_total")
    evaluation.hidden_tests_passed = m.get("hidden_tests_passed")
    evaluation.hidden_tests_total = m.get("hidden_tests_total")
    evaluation.baseline_latency_ms = m.get("baseline_latency_ms")
    evaluation.candidate_latency_ms = m.get("candidate_latency_ms")
    evaluation.improvement_pct = m.get("improvement_pct")
    evaluation.reproduction_latency_ms = m.get("reproduction_latency_ms")
    evaluation.reproduction_improvement_pct = m.get("reproduction_improvement_pct")
    evaluation.integrity_ok = m.get("integrity_ok")
    evaluation.integrity_findings = m.get("integrity_findings")
    evaluation.raw_results = m
    evaluation.event_log = run.events
    evaluation.artifact_path = run.artifact_dir
    evaluation.error_message = run.error
    evaluation.finished_at = datetime.now(timezone.utc)

    # Grok investigation (real tool loop) when xAI configured
    grok_result = None
    if settings.xai_configured and run.workspace:
        try:
            grok_result = await investigate_submission(
                workspace_root=Path(run.workspace),
                contract=contract,
                eval_metrics=m,
                commit_sha=sub.commit_sha or "",
                submitter=sub.submitter_x_username,
                github_url=sub.github_url,
                eval_assets=eval_assets if eval_assets.exists() else None,
            )
            evaluation.grok_investigation = grok_result
        except Exception as e:
            evaluation.grok_investigation = {"error": str(e)}

    # Eligibility from real metrics + investigation (absolute gates)
    eligible, reason = _eligibility(m, contract, grok_result)
    hard_ok = bool(run.ok and eligible)
    evaluation.eval_vector = build_eval_vector(m, hard_gates_ok=hard_ok)

    # Beat-Grok comparison for human / agent challengers (not the Grok baseline itself)
    vs = None
    if (
        hard_ok
        and sub.source_type != SubmissionSource.GROK_BASELINE
        and bounty.baseline_type == BaselineType.GROK_GENERATED
        and bounty.baseline_eval_vector
    ):
        min_over = float((contract.get("benchmark") or {}).get("min_improvement_over_grok_pct") or 5.0)
        vs = compare_to_grok(
            challenger_vector=evaluation.eval_vector,
            grok_vector=bounty.baseline_eval_vector,
            min_improvement_over_grok_pct=min_over,
        )
        sub.beats_grok = bool(vs.get("beats_grok"))
        sub.vs_grok_delta = vs
        if not sub.beats_grok:
            eligible = False
            reason = vs.get("reason") or "Did not beat Grok"
    elif sub.source_type == SubmissionSource.GROK_BASELINE and hard_ok:
        sub.beats_grok = None
        sub.vs_grok_delta = {"verdict": "GROK_BASELINE", "note": "Champion reference"}

    if run.ok and eligible:
        evaluation.status = EvalStatus.SUCCEEDED
        sub.status = SubmissionStatus.COMPLETED
    elif run.ok and not eligible:
        evaluation.status = EvalStatus.SUCCEEDED
        sub.status = SubmissionStatus.INELIGIBLE
        evaluation.error_message = reason
    else:
        evaluation.status = EvalStatus.FAILED
        sub.status = SubmissionStatus.ERROR

    await log_event(
        db,
        event_type="evaluation_finished",
        bounty_id=bounty.id,
        submission_id=sub.id,
        source="evaluator",
        payload={
            "status": sub.status.value,
            "improvement_pct": evaluation.improvement_pct,
            "eligible": eligible,
            "reason": reason,
            "source_type": sub.source_type.value if sub.source_type else None,
            "beats_grok": sub.beats_grok,
            "vs_grok": vs,
            "eval_vector": evaluation.eval_vector,
        },
    )
    await db.commit()

    # Freeze Grok baseline vector on bounty when this IS the Grok submission
    if sub.source_type == SubmissionSource.GROK_BASELINE and evaluation.eval_vector:
        bounty.baseline_eval_vector = evaluation.eval_vector
        bounty.baseline_evaluation_id = evaluation.id
        bounty.baseline_submission_id = sub.id
        bounty.champion_submission_id = sub.id if hard_ok else bounty.champion_submission_id
        await db.commit()

    await recompute_ranking(db, bounty.id)
    await db.refresh(evaluation)
    return evaluation


async def _evaluate_local_paths(bounty, sub, contract, eval_assets):
    """Support local demo variants without GitHub (still real execution)."""
    import shutil
    from app.services.evaluator import (
        EvalRunResult,
        parse_bench_json,
        parse_pytest_counts,
        run_local_command,
        static_integrity_scan,
    )
    from app.config import get_settings
    import json
    import time

    settings = get_settings()
    work_root = Path(settings.workspaces_dir) / str(bounty.id) / str(sub.id)
    artifact_dir = Path(settings.artifacts_dir) / str(bounty.id) / str(sub.id)
    work_root.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    events = []

    def copy_tree(src: Path, dest: Path):
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "variants", ".venv"))

    seed = bounty.seed_repository_url or bounty.repository_url
    base_src = Path(str(seed).replace("file://", ""))
    if not base_src.exists():
        base_src = Path("demo-bounty")
    cand_src = Path(sub.github_url.replace("file://", ""))
    if not cand_src.exists():
        return EvalRunResult(ok=False, error=f"Local path not found: {sub.github_url}", events=events)

    baseline_dir = work_root / "baseline"
    candidate_dir = work_root / "candidate"
    repro_dir = work_root / "repro"
    copy_tree(base_src, baseline_dir)
    copy_tree(cand_src, candidate_dir)
    copy_tree(cand_src, repro_dir)

    build = contract.get("build_command") or "python3 -m pip install -e '.[dev]' -q"
    for d in (baseline_dir, candidate_dir, repro_dir):
        run_local_command(build, cwd=d, timeout=300)

    vis_p = vis_t = hid_p = hid_t = 0
    for t in contract.get("visible_tests") or []:
        cmd = t["command"] if isinstance(t, dict) else t.command
        r = run_local_command(cmd, cwd=candidate_dir, timeout=120)
        p, tot = parse_pytest_counts(r.stdout, r.stderr)
        if tot == 0:
            p, tot = (1, 1) if r.exit_code == 0 else (0, 1)
        vis_p += p
        vis_t += tot
        events.append({"type": "visible_test", "exit": r.exit_code, "passed": p, "total": tot})

    for t in contract.get("hidden_tests") or []:
        cmd = t["command"] if isinstance(t, dict) else t.command
        # rewrite absolute eval path
        if eval_assets and eval_assets.exists():
            cmd = cmd.replace("/eval", str(eval_assets))
            if "eval_assets" not in cmd and "hidden" in cmd:
                pass
        r = run_local_command(cmd, cwd=candidate_dir, timeout=120)
        p, tot = parse_pytest_counts(r.stdout, r.stderr)
        if tot == 0:
            p, tot = (1, 1) if r.exit_code == 0 else (0, 1)
        hid_p += p
        hid_t += tot
        events.append({"type": "hidden_test", "exit": r.exit_code, "passed": p, "total": tot, "cmd": cmd})

    bench_cmd = (contract.get("benchmark") or {}).get("command") or "python bench/bench.py --json"
    br = run_local_command(bench_cmd, cwd=baseline_dir, timeout=180)
    cr = run_local_command(bench_cmd, cwd=candidate_dir, timeout=180)
    rr = run_local_command(bench_cmd, cwd=repro_dir, timeout=180)
    bm = parse_bench_json(br.stdout) if br.exit_code == 0 else {}
    cm = parse_bench_json(cr.stdout) if cr.exit_code == 0 else {}
    rm = parse_bench_json(rr.stdout) if rr.exit_code == 0 else {}
    key = (contract.get("benchmark") or {}).get("metric_key") or "p95_ms"
    base_lat = float(bm.get(key) or 0)
    cand_lat = float(cm.get(key) or 0)
    repro_lat = float(rm.get(key) or 0)
    imp = ((base_lat - cand_lat) / base_lat * 100.0) if base_lat and cand_lat else None
    repro_imp = ((base_lat - repro_lat) / base_lat * 100.0) if base_lat and repro_lat else None
    integrity = static_integrity_scan(
        candidate_dir,
        (contract.get("integrity") or {}).get("protected_paths") or ["eval/"],
    )
    summary = {
        "visible_tests_passed": vis_p,
        "visible_tests_total": vis_t,
        "hidden_tests_passed": hid_p,
        "hidden_tests_total": hid_t,
        "baseline_latency_ms": base_lat or None,
        "candidate_latency_ms": cand_lat or None,
        "improvement_pct": imp,
        "reproduction_latency_ms": repro_lat or None,
        "reproduction_improvement_pct": repro_imp,
        "integrity_ok": integrity["ok"],
        "integrity_findings": integrity,
        "baseline_metrics": bm,
        "candidate_metrics": cm,
        "repro_metrics": rm,
    }
    events.append({"type": "benchmark", "baseline": bm, "candidate": cm, "improvement_pct": imp})
    events.append({"type": "integrity", **integrity})
    (artifact_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    (artifact_dir / "events.json").write_text(json.dumps(events, indent=2, default=str))
    return EvalRunResult(ok=True, metrics=summary, events=events, workspace=str(work_root), artifact_dir=str(artifact_dir))


def _eligibility(
    metrics: dict,
    contract: dict,
    grok_result: Optional[dict],
) -> tuple[bool, str]:
    min_imp = float((contract.get("benchmark") or {}).get("min_improvement_pct") or 25.0)
    vis_p = metrics.get("visible_tests_passed") or 0
    vis_t = metrics.get("visible_tests_total") or 0
    hid_p = metrics.get("hidden_tests_passed") or 0
    hid_t = metrics.get("hidden_tests_total") or 0
    imp = metrics.get("improvement_pct")
    repro = metrics.get("reproduction_improvement_pct")
    integrity_ok = metrics.get("integrity_ok", True)

    if vis_t and vis_p < vis_t:
        return False, "Visible tests failed"
    if hid_t and hid_p < hid_t:
        return False, "Hidden semantic tests failed (likely correctness regression)"
    if not integrity_ok:
        return False, "Integrity scan failed (possible evaluation gaming)"
    if imp is None or imp < min_imp:
        return False, f"Improvement {imp}% below required {min_imp}%"
    if repro is not None and repro < min_imp * 0.8:
        return False, "Improvement did not reproduce in clean sandbox"

    if grok_result and grok_result.get("parsed"):
        parsed = grok_result["parsed"]
        if parsed.get("eligible") is False:
            return False, f"Grok investigation: {parsed.get('summary', 'ineligible')}"
        if parsed.get("recommendation") == "reject":
            return False, f"Grok rejected: {parsed.get('summary', '')}"

    return True, "eligible"


async def recompute_ranking(db: AsyncSession, bounty_id: UUID) -> None:
    """Rank by real metrics among eligible completed submissions. No username shortcuts."""
    r = await db.execute(
        select(Submission)
        .options(selectinload(Submission.evaluation))
        .where(Submission.bounty_id == bounty_id)
    )
    subs = list(r.scalars().all())
    eligible = []
    for s in subs:
        if s.status != SubmissionStatus.COMPLETED or not s.evaluation:
            s.rank = None
            continue
        # In Beat-Grok mode, Grok baseline ranks as champion until beaten
        eligible.append(s)
    # Prefer lower latency (performance), then higher improvement vs seed
    eligible.sort(
        key=lambda s: (
            s.evaluation.candidate_latency_ms if s.evaluation.candidate_latency_ms is not None else 1e18,
            -(s.evaluation.improvement_pct or -1e9),
        )
    )
    for i, s in enumerate(eligible, start=1):
        s.rank = i
    bounty = await db.get(Bounty, bounty_id)
    if bounty and eligible:
        humans_who_beat = [
            s
            for s in eligible
            if s.source_type != SubmissionSource.GROK_BASELINE and s.beats_grok is True
        ]
        if bounty.baseline_type == BaselineType.GROK_GENERATED and not humans_who_beat:
            # only Grok completed / no human beat
            bounty.status = BountyStatus.RANKED
            grok = next((s for s in eligible if s.source_type == SubmissionSource.GROK_BASELINE), None)
            if grok:
                bounty.champion_submission_id = grok.id
        else:
            bounty.status = BountyStatus.RANKED
            if humans_who_beat:
                humans_who_beat.sort(
                    key=lambda s: s.evaluation.candidate_latency_ms
                    if s.evaluation and s.evaluation.candidate_latency_ms is not None
                    else 1e18
                )
                bounty.champion_submission_id = humans_who_beat[0].id
            elif eligible:
                bounty.champion_submission_id = eligible[0].id
    await db.commit()
