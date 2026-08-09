#!/usr/bin/env bash
# Deploy ProofPay API + Web to Fly.io
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Ensure apps exist"
fly apps create proofpay-api --org personal 2>/dev/null || true
fly apps create proofpay-web --org personal 2>/dev/null || true

echo "==> Create volume for workspaces (idempotent)"
fly volumes create proofpay_data --app proofpay-api --region ord --size 3 2>/dev/null || true

echo "==> Create Postgres if needed"
if ! fly postgres list 2>/dev/null | grep -q proofpay-db; then
  fly postgres create --name proofpay-db --region ord --vm-size shared-cpu-1x --volume-size 1 --initial-cluster-size 1 --yes || true
fi
fly postgres attach proofpay-db --app proofpay-api 2>/dev/null || true

echo "==> Set secrets from local .env (names only echoed)"
# shellcheck disable=SC1091
source <(python3 - <<'PY'
from pathlib import Path
import shlex
for line in Path("/Users/shikharsehgal/grokathon/.env").read_text().splitlines():
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line: continue
    k,v=line.split("=",1)
    k=k.strip(); v=v.strip().strip('"').strip("'")
    if k in ("XAI_API_KEY","X_CLIENT_ID","X_CLIENT_SECRET","SECRET_KEY","TOKEN_ENCRYPTION_KEY","X_BEARER_TOKEN","X_API_KEY","X_API_SECRET","GITHUB_TOKEN") and v:
        print(f"export {k}={shlex.quote(v)}")
PY
)

fly secrets set -a proofpay-api \
  XAI_API_KEY="FAKESECRET_i3j4k5l6m7n8o9p0q1r2" \
  X_CLIENT_ID="${X_CLIENT_ID:-}" \
  X_CLIENT_SECRET="${X_CLIENT_SECRET:-}" \
  SECRET_KEY="${SECRET_KEY:-proofpay-fly-secret-change-me}" \
  TOKEN_ENCRYPTION_KEY="${TOKEN_ENCRYPTION_KEY:-}" \
  APP_BASE_URL="https://proofpay-web.fly.dev" \
  API_BASE_URL="https://proofpay-api.fly.dev" \
  CORS_ORIGINS="https://proofpay-web.fly.dev,http://localhost:3000" \
  X_OAUTH_CALLBACK_URL="https://proofpay-web.fly.dev/api/auth/x/callback" \
  X_OAUTH_SCOPES="tweet.read tweet.write users.read offline.access media.write" \
  GROK_BUILD_ENABLED="true" \
  GROK_CLI_PATH="grok" \
  EVALUATOR_DOCKER_ENABLED="false" \
  WORKSPACES_DIR="/data/workspaces" \
  ARTIFACTS_DIR="/data/artifacts" \
  XAI_MODEL="grok-4.5" \
  XAI_BASE_URL="https://api.x.ai/v1"

echo "==> Deploy API (from repo root so Dockerfile can COPY demo seeds)"
fly deploy --config fly.api.toml --app proofpay-api --yes

echo "==> Deploy Web"
fly deploy --config apps/web/fly.toml --app proofpay-web --yes \
  --build-arg NEXT_PUBLIC_API_BASE_URL=https://proofpay-api.fly.dev

echo "==> Seed SearchLab Beat-Grok demo (Grok + 3 agent bots)"
curl -fsS -X POST "https://proofpay-api.fly.dev/api/demo/seed-search-bounty?run_agents=true&generate_grok=true" \
  --max-time 600 | python3 -m json.tool || echo "(seed may still be running — check logs)"

echo "==> Done"
echo "Web: https://proofpay-web.fly.dev"
echo "API: https://proofpay-api.fly.dev"
echo "Update X Developer Console callback to:"
echo "  https://proofpay-web.fly.dev/api/auth/x/callback"
