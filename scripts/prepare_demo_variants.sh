#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/demo-bounty"
for v in alice bob charlie; do
  mkdir -p "variants/$v/tests/visible" "variants/$v/bench" "variants/$v/ranklab"
  cp pyproject.toml "variants/$v/"
  cp ranklab/__init__.py "variants/$v/ranklab/"
  cp -R tests/visible/. "variants/$v/tests/visible/"
  cp bench/bench.py bench/random_inputs.py "variants/$v/bench/"
  # rank.py already lives in variants/$v/ranklab/rank.py
done
echo "Demo variants ready under demo-bounty/variants/{alice,bob,charlie}"
