"""
Grok baseline generation — real Grok Build / Grok Code.

Grok produces an actual repository that becomes a first-class contestant.
No privileged scoring: the generated tree is evaluated by the same pipeline.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings
from app.services import xai_client


PROMPT_VERSION = "beat-grok-v1"


@dataclass
class GenerationResult:
    ok: bool
    repo_path: str
    commit_sha: str
    run_id: str
    model: str
    prompt: str
    method: str  # grok_cli | xai_api | error
    generation_metadata: dict[str, Any]
    error: Optional[str] = None
    deployment_url: Optional[str] = None


def _run(cmd: list[str] | str, *, cwd: Optional[Path] = None, timeout: int = 600, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _init_git_repo(path: Path) -> str:
    _run(["git", "init"], cwd=path, timeout=30)
    _run(["git", "config", "user.email", "proofpay@local"], cwd=path, timeout=10)
    _run(["git", "config", "user.name", "ProofPay Grok Baseline"], cwd=path, timeout=10)
    _run(["git", "add", "-A"], cwd=path, timeout=30)
    _run(
        ["git", "commit", "-m", "Grok Baseline V0 — frozen by ProofPay"],
        cwd=path,
        timeout=30,
    )
    sha = _run(["git", "rev-parse", "HEAD"], cwd=path, timeout=10)
    return (sha.stdout or "").strip()


def _copy_seed(seed: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        seed,
        dest,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".venv",
            "variants",
            "*.egg-info",
            ".pytest_cache",
            "workspaces",
            "artifacts",
        ),
    )


def _build_optimize_prompt(natural_language: str, seed_path: Path) -> str:
    return textwrap.dedent(
        f"""
        You are generating the **Grok Baseline V0** for a ProofPay bounty.

        Goal: produce the best production-quality optimization you can for this repository.
        Do NOT sabotage quality. Humans must genuinely beat your work.

        Repository root: {seed_path}

        Bounty:
        {natural_language}

        Requirements:
        1. Optimize `ranklab/rank.py` for performance while preserving exact semantics.
        2. Do not modify tests/ or eval assets.
        3. Keep the public API: rank(items) and rank_scores(items).
        4. Prefer correct, standard algorithms (e.g. Timsort via sorted).
        5. After editing, ensure tests would still pass conceptually.
        6. Write a short BASELINE.md describing your approach.

        Make the minimal necessary code changes. Prefer editing existing files.
        When done, stop. Do not push remote.
        """
    ).strip()


async def generate_via_xai_api(*, seed_path: Path, dest: Path, natural_language: str) -> GenerationResult:
    """Use xAI chat API to rewrite rank.py (real model). Requires XAI_API_KEY."""
    run_id = uuid.uuid4().hex
    model = get_settings().xai_model
    prompt = _build_optimize_prompt(natural_language, seed_path)
    _copy_seed(seed_path, dest)

    rank_path = dest / "ranklab" / "rank.py"
    original = rank_path.read_text(encoding="utf-8") if rank_path.exists() else ""

    system = (
        "You are Grok optimizing a Python module for a ProofPay baseline. "
        "Return ONLY the full contents of ranklab/rank.py as a Python source file. "
        "No markdown fences."
    )
    user = (
        f"{prompt}\n\n--- CURRENT ranklab/rank.py ---\n{original}\n--- END ---\n"
        "Rewrite the full file with your best optimization."
    )
    content = await xai_client.chat_text(system, user, temperature=0.2)
    # strip fences if model ignores instruction
    content = re.sub(r"^```(?:python)?\n?", "", content.strip())
    content = re.sub(r"\n?```$", "", content.strip())
    if "def rank" not in content:
        return GenerationResult(
            ok=False,
            repo_path=str(dest),
            commit_sha="",
            run_id=run_id,
            model=model,
            prompt=prompt,
            method="xai_api",
            generation_metadata={"raw": content[:2000]},
            error="Model did not return a valid rank() implementation",
        )
    rank_path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    (dest / "BASELINE.md").write_text(
        f"# Grok Baseline V0\n\nGenerated via xAI API (`{model}`).\n\nPrompt version: {PROMPT_VERSION}\n",
        encoding="utf-8",
    )
    sha = _init_git_repo(dest)
    return GenerationResult(
        ok=True,
        repo_path=str(dest),
        commit_sha=sha,
        run_id=run_id,
        model=model,
        prompt=prompt,
        method="xai_api",
        generation_metadata={
            "prompt_version": PROMPT_VERSION,
            "seed": str(seed_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "file": "ranklab/rank.py",
        },
    )


def generate_via_grok_cli(*, seed_path: Path, dest: Path, natural_language: str) -> GenerationResult:
    """Use real Grok Build headless CLI when authenticated."""
    settings = get_settings()
    run_id = uuid.uuid4().hex
    model = "grok-build"
    prompt = _build_optimize_prompt(natural_language, dest)  # after copy, dest is cwd
    _copy_seed(seed_path, dest)
    # re-point prompt to dest
    prompt = _build_optimize_prompt(natural_language, dest)

    cli = settings.grok_cli_path or "grok"
    env = os.environ.copy()
    # Prefer explicit API key if present; otherwise CLI local auth
    if settings.xai_api_key:
        env["XAI_API_KEY"] = settings.xai_api_key

    # Prefer working headless flags verified against current Grok Build CLI.
    # Run with cwd=dest so relative file edits land correctly.
    cmd = [
        cli,
        "-p",
        prompt,
        "--cwd",
        str(dest),
        "--max-turns",
        "25",
        "--yolo",
        "--permission-mode",
        "bypassPermissions",
        "--output-format",
        "plain",
    ]
    try:
        proc = _run(cmd, cwd=dest, timeout=max(settings.evaluator_timeout_sec, 300), env=env)
    except FileNotFoundError:
        return GenerationResult(
            ok=False,
            repo_path=str(dest),
            commit_sha="",
            run_id=run_id,
            model=model,
            prompt=prompt,
            method="grok_cli",
            generation_metadata={},
            error=f"Grok CLI not found at '{cli}'. Install from https://docs.x.ai/build/overview",
        )
    except subprocess.TimeoutExpired:
        return GenerationResult(
            ok=False,
            repo_path=str(dest),
            commit_sha="",
            run_id=run_id,
            model=model,
            prompt=prompt,
            method="grok_cli",
            generation_metadata={},
            error="Grok CLI timed out",
        )

    rank_py = dest / "ranklab" / "rank.py"
    changed = rank_py.exists() and "def rank" in rank_py.read_text(encoding="utf-8", errors="ignore")
    # Detect meaningful edit vs seed
    seed_rank = (seed_path / "ranklab" / "rank.py").read_text(encoding="utf-8", errors="ignore")
    new_rank = rank_py.read_text(encoding="utf-8", errors="ignore") if rank_py.exists() else ""
    if not changed or new_rank.strip() == seed_rank.strip():
        # One more attempt with a tighter edit prompt (still real Grok Build)
        tight = (
            "Only edit ranklab/rank.py: replace the selection-sort implementation of rank() "
            "with the best production-quality version you can (e.g. sorted(items, reverse=True) "
            "if that preserves semantics). Keep rank_scores. Write BASELINE.md with one sentence "
            "describing your approach. Do not modify tests."
        )
        proc2 = _run(
            [
                cli,
                "-p",
                tight,
                "--cwd",
                str(dest),
                "--max-turns",
                "15",
                "--yolo",
                "--permission-mode",
                "bypassPermissions",
                "--output-format",
                "plain",
            ],
            cwd=dest,
            timeout=max(settings.evaluator_timeout_sec, 300),
            env=env,
        )
        new_rank = rank_py.read_text(encoding="utf-8", errors="ignore") if rank_py.exists() else ""
        if new_rank.strip() == seed_rank.strip():
            return GenerationResult(
                ok=False,
                repo_path=str(dest),
                commit_sha="",
                run_id=run_id,
                model=model,
                prompt=prompt,
                method="grok_cli",
                generation_metadata={
                    "stdout_tail": ((proc.stdout or "") + "\n" + (proc2.stdout or ""))[-5000:],
                    "stderr_tail": ((proc.stderr or "") + "\n" + (proc2.stderr or ""))[-3000:],
                    "exit": proc.returncode,
                    "exit2": proc2.returncode,
                },
                error=(
                    "Grok CLI finished without modifying ranklab/rank.py. "
                    f"exit={proc.returncode}/{proc2.returncode}. "
                    "Ensure `grok` is authenticated (local login works; or set XAI_API_KEY)."
                ),
            )
        proc = proc2

    (dest / "BASELINE.md").write_text(
        f"# Grok Baseline V0\n\nGenerated via Grok Build CLI.\n\n"
        f"Prompt version: {PROMPT_VERSION}\nRun: {run_id}\n",
        encoding="utf-8",
    )
    sha = _init_git_repo(dest)
    return GenerationResult(
        ok=True,
        repo_path=str(dest),
        commit_sha=sha,
        run_id=run_id,
        model=model,
        prompt=prompt,
        method="grok_cli",
        generation_metadata={
            "prompt_version": PROMPT_VERSION,
            "seed": str(seed_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cli_exit": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-3000:],
        },
    )


async def generate_optimize_baseline(
    *,
    seed_path: Path,
    out_root: Path,
    natural_language: str,
    prefer_cli: bool = True,
) -> GenerationResult:
    """
    Generate Grok baseline for code-optimization bounties.
    Order: Grok CLI (real Build) → xAI API (if key configured) → hard error (no fake).
    """
    out_root.mkdir(parents=True, exist_ok=True)
    dest = out_root / f"grok-baseline-{uuid.uuid4().hex[:10]}"
    settings = get_settings()
    errors: list[str] = []

    if prefer_cli:
        result = generate_via_grok_cli(
            seed_path=seed_path, dest=dest, natural_language=natural_language
        )
        if result.ok:
            return result
        errors.append(result.error or "cli failed")
        # clean partial dest for next attempt
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)

    if settings.xai_configured:
        result = await generate_via_xai_api(
            seed_path=seed_path, dest=dest, natural_language=natural_language
        )
        if result.ok:
            return result
        errors.append(result.error or "api failed")
    else:
        errors.append("XAI_API_KEY not configured")

    return GenerationResult(
        ok=False,
        repo_path=str(dest),
        commit_sha="",
        run_id=uuid.uuid4().hex,
        model="",
        prompt=_build_optimize_prompt(natural_language, seed_path),
        method="error",
        generation_metadata={"attempts": errors},
        error=(
            "Unable to generate real Grok baseline. "
            "Need either authenticated Grok CLI (`grok` login) or XAI_API_KEY. "
            f"Details: {'; '.join(errors)}"
        ),
    )


def build_eval_vector(metrics: dict[str, Any], *, hard_gates_ok: bool) -> dict[str, Any]:
    """Normalize multi-dimensional evaluation vector from real metrics."""
    vis_p = metrics.get("visible_tests_passed") or 0
    vis_t = metrics.get("visible_tests_total") or 0
    hid_p = metrics.get("hidden_tests_passed") or 0
    hid_t = metrics.get("hidden_tests_total") or 0
    return {
        "hard_gates_ok": hard_gates_ok,
        "functionality": {
            "visible_passed": vis_p,
            "visible_total": vis_t,
            "hidden_passed": hid_p,
            "hidden_total": hid_t,
            "visible_rate": (vis_p / vis_t) if vis_t else None,
            "hidden_rate": (hid_p / hid_t) if hid_t else None,
        },
        "performance": {
            "latency_ms": metrics.get("candidate_latency_ms"),
            "seed_latency_ms": metrics.get("baseline_latency_ms"),
            "improvement_vs_seed_pct": metrics.get("improvement_pct"),
            "reproduction_latency_ms": metrics.get("reproduction_latency_ms"),
            "reproduction_improvement_pct": metrics.get("reproduction_improvement_pct"),
        },
        "integrity": {
            "ok": metrics.get("integrity_ok"),
            "findings": metrics.get("integrity_findings"),
        },
    }


def compare_to_grok(
    *,
    challenger_vector: dict[str, Any],
    grok_vector: dict[str, Any],
    min_improvement_over_grok_pct: float = 5.0,
) -> dict[str, Any]:
    """
    Deterministic comparison: challenger must pass hard gates and beat Grok performance.
    Does not invent scores.
    """
    ch_hard = bool(challenger_vector.get("hard_gates_ok"))
    gk_hard = bool(grok_vector.get("hard_gates_ok"))
    ch_lat = (challenger_vector.get("performance") or {}).get("latency_ms")
    gk_lat = (grok_vector.get("performance") or {}).get("latency_ms")

    delta: dict[str, Any] = {
        "challenger_hard_gates_ok": ch_hard,
        "grok_hard_gates_ok": gk_hard,
        "challenger_latency_ms": ch_lat,
        "grok_latency_ms": gk_lat,
        "min_improvement_over_grok_pct": min_improvement_over_grok_pct,
    }

    if not ch_hard:
        return {
            "beats_grok": False,
            "verdict": "INELIGIBLE",
            "reason": "Challenger failed hard gates",
            "delta": delta,
        }
    if not gk_hard:
        # Grok failed gates — any valid challenger beats it
        return {
            "beats_grok": True,
            "verdict": "VERIFIED_IMPROVEMENT_OVER_GROK",
            "reason": "Grok baseline failed hard gates; valid challenger wins",
            "delta": delta,
        }
    if ch_lat is None or gk_lat is None or gk_lat <= 0:
        return {
            "beats_grok": False,
            "verdict": "INCONCLUSIVE",
            "reason": "Missing latency metrics for comparison",
            "delta": delta,
        }

    improvement_over_grok = ((gk_lat - ch_lat) / gk_lat) * 100.0
    delta["improvement_over_grok_pct"] = improvement_over_grok

    if improvement_over_grok >= min_improvement_over_grok_pct:
        return {
            "beats_grok": True,
            "verdict": "VERIFIED_IMPROVEMENT_OVER_GROK",
            "reason": f"Challenger is {improvement_over_grok:.2f}% faster than Grok (≥{min_improvement_over_grok_pct}%)",
            "delta": delta,
        }
    if improvement_over_grok > 0:
        return {
            "beats_grok": False,
            "verdict": "GROK_REMAINS_CHAMPION",
            "reason": f"Improvement over Grok ({improvement_over_grok:.2f}%) below material threshold {min_improvement_over_grok_pct}%",
            "delta": delta,
        }
    return {
        "beats_grok": False,
        "verdict": "GROK_REMAINS_CHAMPION",
        "reason": f"Challenger is not faster than Grok (Δ={improvement_over_grok:.2f}%)",
        "delta": delta,
    }
