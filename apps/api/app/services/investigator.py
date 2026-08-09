"""
Grok as active investigator: hypothesis → tool experiment → observation → judgment.

Tools execute against the real evaluation workspace / sandbox. Results are never faked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from app.services import xai_client
from app.services.evaluator import parse_bench_json, run_local_command, static_integrity_scan


INVESTIGATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inspect_diff",
            "description": "Show git diff between baseline and candidate commits (stat + patch sample).",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_lines": {"type": "integer", "default": 400},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_file",
            "description": "Read a file from the candidate workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 12000},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_repository",
            "description": "ripgrep-like search in candidate workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "glob": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_dependency_changes",
            "description": "Diff dependency manifests between baseline and candidate.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_protected_paths",
            "description": "List protected/eval-related paths and whether candidate touched them.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_visible_tests",
            "description": "Re-run visible tests in candidate workspace.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_hidden_tests",
            "description": "Re-run hidden tests against candidate.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_benchmark",
            "description": "Run benchmark command in candidate or baseline workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "which": {
                        "type": "string",
                        "enum": ["candidate", "baseline", "repro"],
                        "default": "candidate",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_randomized_inputs",
            "description": "Generate randomized semantic inputs via eval helper if available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "default": 50},
                    "seed": {"type": "integer", "default": 42},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_candidate_on_inputs",
            "description": "Run candidate correctness helper on generated inputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seed": {"type": "integer", "default": 42},
                    "n": {"type": "integer", "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_baseline_on_inputs",
            "description": "Run baseline correctness helper on same generated inputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seed": {"type": "integer", "default": 42},
                    "n": {"type": "integer", "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_outputs",
            "description": "Compare baseline vs candidate outputs for randomized inputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seed": {"type": "integer", "default": 99},
                    "n": {"type": "integer", "default": 100},
                },
            },
        },
    },
]


class WorkspaceTools:
    def __init__(
        self,
        *,
        baseline_dir: Path,
        candidate_dir: Path,
        repro_dir: Optional[Path],
        contract: dict[str, Any],
        eval_assets: Optional[Path],
        prior_metrics: Optional[dict[str, Any]] = None,
    ) -> None:
        self.baseline_dir = baseline_dir
        self.candidate_dir = candidate_dir
        self.repro_dir = repro_dir
        self.contract = contract
        self.eval_assets = eval_assets
        self.prior_metrics = prior_metrics or {}

    def _ws(self, which: str) -> Path:
        if which == "baseline":
            return self.baseline_dir
        if which == "repro" and self.repro_dir:
            return self.repro_dir
        return self.candidate_dir

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        if name == "inspect_diff":
            return self._inspect_diff(int(args.get("max_lines") or 400))
        if name == "inspect_file":
            return self._inspect_file(args["path"], int(args.get("max_chars") or 12000))
        if name == "search_repository":
            return self._search(args["pattern"], args.get("glob"))
        if name == "inspect_dependency_changes":
            return self._deps()
        if name == "inspect_protected_paths":
            return static_integrity_scan(
                self.candidate_dir,
                (self.contract.get("integrity") or {}).get("protected_paths")
                or ["tests/", "eval/"],
            )
        if name == "run_visible_tests":
            return self._run_tests("visible")
        if name == "run_hidden_tests":
            return self._run_tests("hidden")
        if name == "run_benchmark":
            return self._run_bench(args.get("which") or "candidate")
        if name == "generate_randomized_inputs":
            return self._randomized(int(args.get("n") or 50), int(args.get("seed") or 42))
        if name == "run_candidate_on_inputs":
            return self._run_on_inputs("candidate", int(args.get("n") or 50), int(args.get("seed") or 42))
        if name == "run_baseline_on_inputs":
            return self._run_on_inputs("baseline", int(args.get("n") or 50), int(args.get("seed") or 42))
        if name == "compare_outputs":
            return self._compare(int(args.get("n") or 100), int(args.get("seed") or 99))
        return {"error": f"Unknown tool {name}"}

    def _inspect_diff(self, max_lines: int) -> str:
        # Diff candidate vs baseline trees via git if both are git repos
        try:
            r = subprocess.run(
                ["diff", "-ru", "--exclude=.git", str(self.baseline_dir), str(self.candidate_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            out = r.stdout or r.stderr or ""
            lines = out.splitlines()
            return "\n".join(lines[:max_lines]) + (f"\n...[{len(lines)-max_lines} more lines]" if len(lines) > max_lines else "")
        except Exception as e:
            return f"diff failed: {e}"

    def _inspect_file(self, path: str, max_chars: int) -> str:
        p = (self.candidate_dir / path).resolve()
        if not str(p).startswith(str(self.candidate_dir.resolve())):
            return "error: path escapes workspace"
        if not p.exists():
            return f"error: not found: {path}"
        data = p.read_text(encoding="utf-8", errors="replace")
        return data[:max_chars]

    def _search(self, pattern: str, glob: Optional[str]) -> str:
        cmd = ["rg", "-n", pattern, str(self.candidate_dir)]
        if glob:
            cmd.extend(["--glob", glob])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return (r.stdout or r.stderr or "")[:20000]
        except FileNotFoundError:
            # fallback grep
            r = subprocess.run(
                ["grep", "-RIn", pattern, str(self.candidate_dir)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return (r.stdout or "")[:20000]

    def _deps(self) -> str:
        names = [
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "Cargo.toml",
            "go.mod",
        ]
        parts = []
        for n in names:
            b = self.baseline_dir / n
            c = self.candidate_dir / n
            if b.exists() or c.exists():
                parts.append(f"## {n}")
                if b.exists():
                    parts.append("--- baseline ---")
                    parts.append(b.read_text(encoding="utf-8", errors="replace")[:4000])
                if c.exists():
                    parts.append("--- candidate ---")
                    parts.append(c.read_text(encoding="utf-8", errors="replace")[:4000])
        return "\n".join(parts) or "No dependency manifests found."

    def _run_tests(self, kind: str) -> dict[str, Any]:
        key = "visible_tests" if kind == "visible" else "hidden_tests"
        results = []
        for t in self.contract.get(key) or []:
            cmd = t["command"] if isinstance(t, dict) else t.command
            # rewrite /eval paths to local assets if needed
            if self.eval_assets and "/eval" in cmd:
                cmd = cmd.replace("/eval", str(self.eval_assets))
            r = run_local_command(cmd, cwd=self.candidate_dir, timeout=120)
            results.append(
                {
                    "command": cmd,
                    "exit_code": r.exit_code,
                    "stdout_tail": r.stdout[-2000:],
                    "stderr_tail": r.stderr[-1000:],
                }
            )
        return {"tests": results}

    def _run_bench(self, which: str) -> dict[str, Any]:
        bench = self.contract.get("benchmark") or {}
        cmd = bench.get("command") or "python bench/bench.py --json"
        if self.eval_assets and "/eval" in cmd:
            cmd = cmd.replace("/eval", str(self.eval_assets))
        ws = self._ws(which)
        r = run_local_command(cmd, cwd=ws, timeout=180)
        metrics = None
        err = None
        try:
            metrics = parse_bench_json(r.stdout)
        except Exception as e:
            err = str(e)
        return {
            "which": which,
            "exit_code": r.exit_code,
            "metrics": metrics,
            "parse_error": err,
            "stdout_tail": r.stdout[-2000:],
            "stderr_tail": r.stderr[-1000:],
        }

    def _randomized(self, n: int, seed: int) -> dict[str, Any]:
        helper = None
        for candidate in [
            self.eval_assets / "random_inputs.py" if self.eval_assets else None,
            self.candidate_dir / "bench" / "random_inputs.py",
            self.baseline_dir / "bench" / "random_inputs.py",
        ]:
            if candidate and candidate.exists():
                helper = candidate
                break
        if not helper:
            return {
                "error": "No random_inputs.py helper found in eval assets or repo",
                "hint": "ProofPay demo bounty ships bench/random_inputs.py",
            }
        r = run_local_command(
            f"python {helper} --n {n} --seed {seed} --json",
            cwd=self.candidate_dir,
            timeout=60,
        )
        return {"exit_code": r.exit_code, "stdout": r.stdout[:10000], "stderr": r.stderr[:2000]}

    def _run_on_inputs(self, which: str, n: int, seed: int) -> dict[str, Any]:
        ws = self._ws(which)
        helper = ws / "bench" / "run_inputs.py"
        if self.eval_assets and (self.eval_assets / "run_inputs.py").exists():
            helper = self.eval_assets / "run_inputs.py"
        if not helper.exists():
            # try module form
            r = run_local_command(
                f"python -c \"from ranklab.rank import rank; import random; "
                f"random.seed({seed}); "
                f"print(sum(len(rank(list(range(i%20)))) for i in range({n})))\"",
                cwd=ws,
                timeout=60,
            )
            return {"exit_code": r.exit_code, "stdout": r.stdout, "stderr": r.stderr}
        r = run_local_command(
            f"python {helper} --n {n} --seed {seed} --json",
            cwd=ws,
            timeout=90,
        )
        return {"exit_code": r.exit_code, "stdout": r.stdout[:10000], "stderr": r.stderr[:2000]}

    def _compare(self, n: int, seed: int) -> dict[str, Any]:
        script = None
        if self.eval_assets and (self.eval_assets / "compare_outputs.py").exists():
            script = self.eval_assets / "compare_outputs.py"
        if script is None:
            # Inline compare for ranklab demo
            code = f"""
import json, random, sys
sys.path.insert(0, {str(self.baseline_dir)!r})
from ranklab.rank import rank as base_rank
sys.path.insert(0, {str(self.candidate_dir)!r})
# reload candidate
import importlib
if 'ranklab.rank' in sys.modules:
    del sys.modules['ranklab.rank']
if 'ranklab' in sys.modules:
    del sys.modules['ranklab']
sys.path.insert(0, {str(self.candidate_dir)!r})
from ranklab.rank import rank as cand_rank
random.seed({seed})
mismatches = []
for i in range({n}):
    items = [random.randint(-1000,1000) for _ in range(random.randint(0,40))]
    try:
        b = base_rank(items)
        c = cand_rank(list(items))
        if b != c:
            mismatches.append({{"i": i, "items": items[:20], "base": b[:20] if isinstance(b,list) else b, "cand": c[:20] if isinstance(c,list) else c}})
    except Exception as e:
        mismatches.append({{"i": i, "error": str(e)}})
print(json.dumps({{"n": {n}, "mismatches": len(mismatches), "examples": mismatches[:5]}}))
"""
            r = run_local_command(f"python - <<'PY'\n{code}\nPY", cwd=self.candidate_dir, timeout=90)
            return {"exit_code": r.exit_code, "stdout": r.stdout[:10000], "stderr": r.stderr[:2000]}
        r = run_local_command(
            f"python {script} --baseline {self.baseline_dir} --candidate {self.candidate_dir} --n {n} --seed {seed}",
            cwd=self.candidate_dir,
            timeout=90,
        )
        return {"exit_code": r.exit_code, "stdout": r.stdout[:10000], "stderr": r.stderr[:2000]}


async def investigate_submission(
    *,
    workspace_root: Path,
    contract: dict[str, Any],
    eval_metrics: dict[str, Any],
    commit_sha: str,
    submitter: Optional[str],
    github_url: str,
    eval_assets: Optional[Path] = None,
) -> dict[str, Any]:
    tools = WorkspaceTools(
        baseline_dir=workspace_root / "baseline",
        candidate_dir=workspace_root / "candidate",
        repro_dir=(workspace_root / "repro") if (workspace_root / "repro").exists() else None,
        contract=contract,
        eval_assets=eval_assets,
        prior_metrics=eval_metrics,
    )

    system = (
        "You are ProofPay's adversarial verifier. You investigate candidate patches for "
        "legitimate performance improvements versus gaming, overfitting, or semantic regression. "
        "Use tools to form hypotheses, run experiments, and update your judgment. "
        "Never invent tool results. Cite concrete observations.\n\n"
        "Return a final JSON judgment with keys: "
        "eligible (bool), risk_level (low|medium|high|critical), "
        "summary (str), mechanism (str), concerns (list[str]), "
        "experiments_run (list[str]), recommendation (approve|reject|needs_review)."
    )
    user = json.dumps(
        {
            "submitter": submitter,
            "github_url": github_url,
            "commit_sha": commit_sha,
            "eval_metrics": eval_metrics,
            "contract_summary": contract.get("summary"),
            "acceptance": contract.get("acceptance_criteria"),
            "instructions": (
                "1) Inspect the diff and suspicious patterns. "
                "2) If speedup looks too large or integrity flags exist, run randomized compare. "
                "3) Check hidden-test implications. "
                "4) Conclude eligibility."
            ),
        },
        indent=2,
        default=str,
    )

    result = await xai_client.tool_loop(
        system=system,
        user=user,
        tools=INVESTIGATOR_TOOLS,
        tool_executor=tools.execute,
        max_rounds=10,
    )

    final = result.get("final") or ""
    judgment: dict[str, Any] = {"raw_final": final, "transcript": result.get("transcript")}
    # Try parse JSON from final
    try:
        start = final.find("{")
        end = final.rfind("}")
        if start >= 0 and end > start:
            judgment["parsed"] = json.loads(final[start : end + 1])
    except json.JSONDecodeError:
        judgment["parsed"] = {
            "eligible": None,
            "summary": final[:2000],
            "recommendation": "needs_review",
        }
    return judgment
