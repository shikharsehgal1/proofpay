#!/usr/bin/env python3
"""Evaluator-side bench wrapper (same semantics as public bench)."""

import runpy
from pathlib import Path

# Prefer workspace public bench if present
ws_bench = Path("/workspace/bench/bench.py")
local = Path(__file__).with_name("bench_inner.py")
if ws_bench.exists():
    runpy.run_path(str(ws_bench), run_name="__main__")
else:
    runpy.run_path(str(local), run_name="__main__")
