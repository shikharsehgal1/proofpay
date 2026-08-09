#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill XAI_API_KEY and X_* credentials."
fi

echo "Starting Postgres + Redis..."
docker compose up -d db redis

echo "Installing API deps..."
cd "$ROOT/apps/api"
if command -v uv >/dev/null 2>&1; then
  uv venv .venv || true
  # shellcheck disable=SC1091
  source .venv/bin/activate
  uv pip install -e .
else
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -e .
fi

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://proofpay:proofpay@localhost:5432/proofpay}"
export DATABASE_URL_SYNC="${DATABASE_URL_SYNC:-postgresql://proofpay:proofpay@localhost:5432/proofpay}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export WORKSPACES_DIR="$ROOT/workspaces"
export ARTIFACTS_DIR="$ROOT/artifacts"
mkdir -p "$WORKSPACES_DIR" "$ARTIFACTS_DIR"

# load .env
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

echo "Starting API on :8000..."
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
API_PID=$!

echo "Installing web deps..."
cd "$ROOT/apps/web"
npm install
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}"
export NEXT_PUBLIC_DEMO_REPO="$ROOT/demo-bounty"
echo "Starting web on :3000..."
npm run dev &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT
wait
