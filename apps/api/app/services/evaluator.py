"""
Real evaluation pipeline.

Every metric originates from actual process/container execution.
No seeded demo result fixtures. No username-based winner shortcuts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float


@dataclass
class EvalRunResult:
    ok: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    workspace: Optional[str] = None
    artifact_dir: Optional[str] = None


def _log(events: list, event_type: str, **payload: Any) -> None:
    events.append({"ts": time.time(), "type": event_type, **payload})


def _clean_env(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """
    Build an eval environment that does not inherit the API venv.
    Candidate builds must use system/python3.12 tooling, not the API's .venv.
    """
    merged = os.environ.copy()
    # Drop virtualenv hints
    for k in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        merged.pop(k, None)
    # Prefer system-ish PATH without active venv bin first
    path_parts = [p for p in merged.get("PATH", "").split(":") if p and ".venv" not in p]
    # Ensure common locations
    for p in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"):
        if p not in path_parts:
            path_parts.append(p)
    merged["PATH"] = ":".join(path_parts)
    # Force plain python3 discovery
    merged["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    if extra:
        merged.update(extra)
    return merged


def run_local_command(
    command: str,
    *,
    cwd: Path,
    env: Optional[dict[str, str]] = None,
    timeout: int = 120,
) -> CommandResult:
    merged = _clean_env(env)
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            env=merged,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = (time.perf_counter() - start) * 1000
        return CommandResult(
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_ms=duration,
        )
    except subprocess.TimeoutExpired as exc:
        duration = (time.perf_counter() - start) * 1000
        return CommandResult(
            command=command,
            exit_code=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=f"TIMEOUT after {timeout}s",
            duration_ms=duration,
        )


def _materialize_source(source: str, commit_sha: str, dest: Path) -> None:
    """Clone a git remote at commit_sha, or copy a local directory tree."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)

    local = source.removeprefix("file://")
    if not source.startswith("http") and Path(local).exists():
        shutil.copytree(
            local,
            dest,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", ".venv", "variants", "workspaces", "artifacts", "*.egg-info"
            ),
        )
        return

    clone_url = source
    r = subprocess.run(
        ["git", "clone", "--filter=blob:none", clone_url, str(dest)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {r.stderr}")
    if commit_sha in ("", "HEAD", "local", "local-baseline") or commit_sha.startswith("local-"):
        return
    r2 = subprocess.run(
        ["git", "checkout", commit_sha],
        cwd=str(dest),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r2.returncode != 0:
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", commit_sha],
            cwd=str(dest),
            capture_output=True,
            text=True,
            timeout=120,
        )
        r3 = subprocess.run(
            ["git", "checkout", commit_sha],
            cwd=str(dest),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r3.returncode != 0:
            raise RuntimeError(f"git checkout {commit_sha} failed: {r3.stderr}")


def clone_commit(clone_url: str, commit_sha: str, dest: Path) -> None:
    _materialize_source(clone_url, commit_sha, dest)


def run_in_docker(
    workspace: Path,
    command: str,
    *,
    image: str,
    timeout: int,
    memory_mb: int,
    cpus: float,
    mounts: Optional[list[tuple[Path, str, str]]] = None,
    env: Optional[dict[str, str]] = None,
) -> CommandResult:
    """Execute command inside isolated Docker container with workspace mounted read-write."""
    settings = get_settings()
    if not settings.evaluator_docker_enabled:
        return run_local_command(command, cwd=workspace, env=env, timeout=timeout)

    name = f"proofpay-eval-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--memory",
        f"{memory_mb}m",
        "--cpus",
        str(cpus),
        "-v",
        f"{workspace.resolve()}:/workspace:rw",
        "-w",
        "/workspace",
    ]
    if mounts:
        for host, container, mode in mounts:
            cmd.extend(["-v", f"{host.resolve()}:{container}:{mode}"])
    if env:
        for k, v in env.items():
            cmd.extend(["-e", f"{k}={v}"])
    cmd.extend([image, "bash", "-lc", command])

    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
        duration = (time.perf_counter() - start) * 1000
        return CommandResult(
            command=" ".join(cmd[-3:]) + f" # {command}",
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_ms=duration,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        duration = (time.perf_counter() - start) * 1000
        return CommandResult(
            command=command,
            exit_code=124,
            stdout="",
            stderr=f"Docker eval TIMEOUT after {timeout}s",
            duration_ms=duration,
        )
    except FileNotFoundError:
        # Docker binary missing — fall back to local process isolation (still real execution)
        return run_local_command(command, cwd=workspace, env=env, timeout=timeout)


def parse_pytest_counts(stdout: str, stderr: str) -> tuple[int, int]:
    """Parse 'N passed' style summaries. Returns (passed, total)."""
    import re

    text = stdout + "\n" + stderr
    passed = failed = skipped = errors = 0
    m = re.search(r"(\d+)\s+passed", text)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", text)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", text)
    if m:
        skipped = int(m.group(1))
    m = re.search(r"(\d+)\s+error", text)
    if m:
        errors = int(m.group(1))
    total = passed + failed + errors
    if total == 0 and "passed" not in text and "failed" not in text:
        # fallback: exit-code based handled by caller
        return 0, 0
    return passed, total


def parse_bench_json(stdout: str) -> dict[str, Any]:
    # Find last JSON object in stdout
    text = stdout.strip()
    if not text:
        raise ValueError("Empty benchmark stdout")
    # Try whole stdout
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Scan lines reverse
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    # Substring
    start = text.rfind("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"No JSON metrics found in benchmark output: {text[:500]}")


def static_integrity_scan(workspace: Path, protected_paths: list[str]) -> dict[str, Any]:
    """
    Static integrity checks (real filesystem inspection — not Grok hallucination).
    Flags protected-path modifications and common gaming patterns.
    """
    findings: list[dict[str, Any]] = []
    # Protected path edits: candidates shouldn't ship modified hidden tests
    for pp in protected_paths:
        p = workspace / pp.rstrip("/")
        # Only flag if path exists inside candidate and looks like eval assets
        if p.exists() and ("hidden" in str(p).lower() or str(pp).startswith("eval")):
            findings.append(
                {
                    "severity": "medium",
                    "code": "protected_path_present",
                    "path": pp,
                    "detail": "Protected/eval path present in candidate tree",
                }
            )

    # Scan python files for gaming patterns
    patterns = [
        (r"PROOFPAY_BENCH|PROOFPAY_EVAL|BENCH_MODE", "env_detection"),
        (r"sys\.argv.*bench|os\.environ\.get\(['\"]BENCH", "bench_argv_detection"),
        (r"hardcoded|MAGIC_BENCH|KNOWN_INPUTS", "hardcode_hint"),
        (r"if\s+.*benchmark|detect_benchmark", "benchmark_detection"),
    ]
    import re

    for py in workspace.rglob("*.py"):
        if ".git" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat, code in patterns:
            if re.search(pat, content, re.I):
                findings.append(
                    {
                        "severity": "high",
                        "code": code,
                        "path": str(py.relative_to(workspace)),
                        "detail": f"Matched pattern /{pat}/",
                    }
                )

    ok = not any(f["severity"] == "high" for f in findings)
    return {"ok": ok, "findings": findings}


async def evaluate_submission(
    *,
    bounty_id: str,
    submission_id: str,
    clone_url: str,
    commit_sha: str,
    baseline_clone_url: str,
    baseline_commit_sha: str,
    contract: dict[str, Any],
    eval_assets_dir: Optional[Path] = None,
) -> EvalRunResult:
    """
    Full evaluation:
      1. Clone baseline + candidate at exact SHAs
      2. Build both
      3. Run visible tests on candidate
      4. Run hidden tests (from protected eval assets)
      5. Benchmark baseline + candidate
      6. Integrity scan
      7. Fresh-sandbox reproduction of candidate benchmark
    """
    settings = get_settings()
    events: list[dict[str, Any]] = []
    work_root = Path(settings.workspaces_dir) / str(bounty_id) / str(submission_id)
    artifact_dir = Path(settings.artifacts_dir) / str(bounty_id) / str(submission_id)
    work_root.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    baseline_dir = work_root / "baseline"
    candidate_dir = work_root / "candidate"
    repro_dir = work_root / "repro"

    try:
        _log(events, "clone_start", clone_url=clone_url, sha=commit_sha)
        clone_commit(baseline_clone_url, baseline_commit_sha, baseline_dir)
        clone_commit(clone_url, commit_sha, candidate_dir)
        _log(events, "clone_done")

        build_cmd = contract.get("build_command") or "python3 -m pip install -e '.[dev]' -q || true"
        image = settings.evaluator_image
        timeout = settings.evaluator_timeout_sec
        mem = settings.evaluator_memory_mb
        cpus = settings.evaluator_cpus

        # Prefer local venv execution if docker image not built — still real.
        use_docker = settings.evaluator_docker_enabled and _docker_image_exists(image)

        def exec_cmd(ws: Path, cmd: str, t: int = 180, mounts=None, env=None) -> CommandResult:
            if use_docker:
                return run_in_docker(
                    ws,
                    cmd,
                    image=image,
                    timeout=t,
                    memory_mb=mem,
                    cpus=cpus,
                    mounts=mounts,
                    env=env,
                )
            return run_local_command(cmd, cwd=ws, env=env, timeout=t)

        _log(events, "build_baseline")
        b_build = exec_cmd(baseline_dir, build_cmd, t=300)
        events.append({"type": "build_baseline_result", "exit": b_build.exit_code, "stderr": b_build.stderr[-2000:]})
        _log(events, "build_candidate")
        c_build = exec_cmd(candidate_dir, build_cmd, t=300)
        events.append({"type": "build_candidate_result", "exit": c_build.exit_code, "stderr": c_build.stderr[-2000:]})

        # Mount eval assets (hidden tests + bench) if provided
        mounts = None
        if eval_assets_dir and eval_assets_dir.exists():
            mounts = [(eval_assets_dir, "/eval", "ro")]

        # Visible tests
        visible = contract.get("visible_tests") or []
        vis_passed = vis_total = 0
        for tspec in visible:
            cmd = tspec["command"] if isinstance(tspec, dict) else tspec.command
            r = exec_cmd(candidate_dir, cmd, t=180, mounts=mounts)
            p, tot = parse_pytest_counts(r.stdout, r.stderr)
            if tot == 0:
                # treat exit code
                if r.exit_code == 0:
                    p, tot = 1, 1
                else:
                    p, tot = 0, 1
            vis_passed += p
            vis_total += tot
            events.append(
                {
                    "type": "visible_test",
                    "command": cmd,
                    "exit": r.exit_code,
                    "passed": p,
                    "total": tot,
                    "stdout_tail": r.stdout[-1500:],
                }
            )

        # Hidden tests
        hidden = contract.get("hidden_tests") or []
        hid_passed = hid_total = 0
        for tspec in hidden:
            cmd = tspec["command"] if isinstance(tspec, dict) else tspec.command
            r = exec_cmd(candidate_dir, cmd, t=180, mounts=mounts)
            p, tot = parse_pytest_counts(r.stdout, r.stderr)
            if tot == 0:
                if r.exit_code == 0:
                    p, tot = 1, 1
                else:
                    p, tot = 0, 1
            hid_passed += p
            hid_total += tot
            events.append(
                {
                    "type": "hidden_test",
                    "command": cmd,
                    "exit": r.exit_code,
                    "passed": p,
                    "total": tot,
                    "stdout_tail": r.stdout[-1500:],
                }
            )

        # Benchmark
        bench = contract.get("benchmark") or {}
        bench_cmd = bench.get("command") or "python /eval/bench.py --json"
        metric_key = bench.get("metric_key") or "p95_ms"

        _log(events, "bench_baseline")
        br = exec_cmd(baseline_dir, bench_cmd, t=300, mounts=mounts)
        _log(events, "bench_candidate")
        cr = exec_cmd(candidate_dir, bench_cmd, t=300, mounts=mounts)

        baseline_metrics = {}
        candidate_metrics = {}
        try:
            baseline_metrics = parse_bench_json(br.stdout)
        except Exception as e:
            events.append({"type": "bench_baseline_parse_error", "error": str(e), "stdout": br.stdout[-2000:]})
        try:
            candidate_metrics = parse_bench_json(cr.stdout)
        except Exception as e:
            events.append({"type": "bench_candidate_parse_error", "error": str(e), "stdout": cr.stdout[-2000:]})

        base_lat = float(baseline_metrics.get(metric_key) or baseline_metrics.get("latency_ms") or 0)
        cand_lat = float(candidate_metrics.get(metric_key) or candidate_metrics.get("latency_ms") or 0)
        improvement = None
        if base_lat > 0 and cand_lat > 0:
            # lower latency is better
            if not bench.get("higher_is_better", False):
                improvement = ((base_lat - cand_lat) / base_lat) * 100.0
            else:
                improvement = ((cand_lat - base_lat) / base_lat) * 100.0

        events.append(
            {
                "type": "benchmark",
                "baseline": baseline_metrics,
                "candidate": candidate_metrics,
                "improvement_pct": improvement,
            }
        )

        # Integrity
        integrity = contract.get("integrity") or {}
        protected = integrity.get("protected_paths") or ["tests/", "bench/", "eval/"]
        integrity_result = static_integrity_scan(candidate_dir, protected)
        events.append({"type": "integrity", **integrity_result})

        # Reproduction in fresh workspace
        _log(events, "repro_clone")
        clone_commit(clone_url, commit_sha, repro_dir)
        exec_cmd(repro_dir, build_cmd, t=300)
        rr = exec_cmd(repro_dir, bench_cmd, t=300, mounts=mounts)
        repro_metrics = {}
        try:
            repro_metrics = parse_bench_json(rr.stdout)
        except Exception as e:
            events.append({"type": "repro_parse_error", "error": str(e)})
        repro_lat = float(repro_metrics.get(metric_key) or repro_metrics.get("latency_ms") or 0)
        repro_imp = None
        if base_lat > 0 and repro_lat > 0:
            if not bench.get("higher_is_better", False):
                repro_imp = ((base_lat - repro_lat) / base_lat) * 100.0
            else:
                repro_imp = ((repro_lat - base_lat) / base_lat) * 100.0
        events.append({"type": "reproduction", "metrics": repro_metrics, "improvement_pct": repro_imp})

        # Persist artifacts
        (artifact_dir / "events.json").write_text(json.dumps(events, indent=2, default=str))
        summary = {
            "visible_tests_passed": vis_passed,
            "visible_tests_total": vis_total,
            "hidden_tests_passed": hid_passed,
            "hidden_tests_total": hid_total,
            "baseline_latency_ms": base_lat or None,
            "candidate_latency_ms": cand_lat or None,
            "improvement_pct": improvement,
            "reproduction_latency_ms": repro_lat or None,
            "reproduction_improvement_pct": repro_imp,
            "integrity_ok": integrity_result["ok"],
            "integrity_findings": integrity_result,
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "repro_metrics": repro_metrics,
        }
        (artifact_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

        ok = True
        return EvalRunResult(
            ok=ok,
            metrics=summary,
            events=events,
            workspace=str(work_root),
            artifact_dir=str(artifact_dir),
        )
    except Exception as exc:
        _log(events, "fatal_error", error=str(exc))
        (artifact_dir / "events.json").write_text(json.dumps(events, indent=2, default=str))
        return EvalRunResult(
            ok=False,
            metrics={},
            events=events,
            error=str(exc),
            workspace=str(work_root),
            artifact_dir=str(artifact_dir),
        )


def _docker_image_exists(image: str) -> bool:
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def ensure_evaluator_image() -> bool:
    """Build local evaluator image if Dockerfile present."""
    root = Path(__file__).resolve().parents[3]  # repo root approx
    dockerfile = root / "docker" / "evaluator" / "Dockerfile"
    if not dockerfile.exists():
        # try monorepo root relative
        dockerfile = Path("docker/evaluator/Dockerfile")
    if not dockerfile.exists():
        return False
    settings = get_settings()
    r = subprocess.run(
        [
            "docker",
            "build",
            "-t",
            settings.evaluator_image,
            "-f",
            str(dockerfile),
            str(dockerfile.parent),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    return r.returncode == 0
