# ProofPay

**Get Grok to build it. Pay humans only if they can beat it.**

ProofPay is **AI escrow for verifiable work**. Grok produces **Baseline V0** first — a real repository, pinned commit, same evaluator as every human challenger. Humans win only with **verified improvement over Grok**.

> **X Money:** There is **no public developer API** for X Money available to this project. Settlement stops at **`VERIFIED` / `READY_FOR_SETTLEMENT`**. We do not fake payouts.

See [`INTEGRATION_MATRIX.md`](./INTEGRATION_MATRIX.md) for verified capability status.

---

## Grok Reply App Bot (sibling surface)

Dedicated X bot account (not your personal OAuth). When mentioned, Grok generates a **self-contained mini-app** and replies under the tweet with a live link (`/a/{slug}`).

```bash
# Status (no secrets)
curl $API/api/reply-app/status

# Dry-run generation (needs XAI_API_KEY only)
curl -X POST $API/api/reply-app/dry-run \
  -H 'content-type: application/json' \
  -d '{"text":"@bot make a split-the-bill tip calculator"}'

# Scan recent tweets from watchlist (drafts by default — no auto-reply)
curl -X POST $API/api/reply-app/scan-opportunities \
  -H 'content-type: application/json' -d '{}'
```

Wire the new bot account later via `REPLY_APP_BOT_*` env vars. Full architecture: [`docs/REPLY_APP_BOT.md`](./docs/REPLY_APP_BOT.md).

---

## Beat Grok (primary mode)

```text
Request → Grok Build → frozen commit → same evaluator → open BEAT GROK
       → human challengers → same evaluator
       → VERIFIED IMPROVEMENT OVER GROK  |  GROK REMAINS CHAMPION
```

Grok is a **first-class contestant** (`source_type=grok_baseline`). No privileged scores.

Classic **optimize** mode (user-provided seed, no Grok baseline) still works.

---

## Architecture

| Component | Stack |
| --------- | ----- |
| `apps/web` | Next.js UI |
| `apps/api` | FastAPI, SQLAlchemy, real xAI + X clients + Grok Build CLI |
| `demo-bounty` | RankLab seed + Alice / Bob / Charlie challengers |
| `demo-search` | Multi-metric SearchLab Beat-Grok seed |
| `docker/evaluator` | Isolated Python eval image |
| Postgres + Redis | Persistent state + optional job queue |
| **Reply App Bot** | `@mention` → Grok mini-app → reply under tweet ([docs/REPLY_APP_BOT.md](./docs/REPLY_APP_BOT.md)) |

**No hardcoded winners.** Alice/Bob/Charlie exercise the same pipeline as production submissions.

| Variant | Behavior | Typical outcome vs Grok |
| ------- | -------- | ----------------------- |
| **Grok V0** | Real Grok Build optimization | Champion unless beaten |
| **Alice** | Legitimate `sorted(..., reverse=True)` | May tie / lose if Grok already optimal |
| **Bob** | Drops duplicates via `set()` | Hard-gate fail (correctness) |
| **Charlie** | Bench distribution gaming + env probes | Integrity fail |

---

## Quick start

### Prerequisites

- Docker (Postgres, Redis)
- Node 20+
- Python 3.11+ (`uv` recommended)
- Authenticated `grok` CLI **or** `XAI_API_KEY`
- X Developer App for OAuth / posts

### Configure

```bash
cp .env.example .env
# Fill XAI_API_KEY and/or rely on local `grok` login
# Fill X_CLIENT_ID / X_CLIENT_SECRET for X publish
```

### Run

```bash
docker compose up -d db redis
./scripts/prepare_demo_variants.sh

cd apps/api
source .venv/bin/activate   # or uv venv + uv pip install -e .
export DATABASE_URL=postgresql+asyncpg://proofpay:proofpay@localhost:5432/proofpay
export WORKSPACES_DIR=../../workspaces ARTIFACTS_DIR=../../artifacts
export GROK_BUILD_ENABLED=true GROK_CLI_PATH=grok
uvicorn app.main:app --reload --port 8000
```

```bash
cd apps/web && npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

Open http://localhost:3000 — `/status` shows honest integration gates.

---

## Verified vertical slice (this machine)

Real Grok Build + real evaluator (no fixtures):

| Contestant | Source | Status | Latency | Notes |
| ---------- | ------ | ------ | ------- | ----- |
| **Grok** | `grok_baseline` @ `0eb3be76…` | completed #1 | **0.041 ms** | +99.5% vs seed; 7/7 vis, 4/4 hid |
| Alice | human | ineligible | 0.043 ms | Valid but **did not beat Grok** (Δ −4.65%) |
| Bob | human | ineligible | — | Correctness regression |
| Charlie | human | ineligible | 0.074 ms | Integrity gaming flagged |

**Verdict: `GROK_REMAINS_CHAMPION`**

### UI / API flow

1. Dashboard → mode **Beat Grok** → create bounty on `demo-bounty` seed  
2. Approve contract (+ seed metrics)  
3. **Generate Grok Baseline V0** → `POST /api/bounties/{id}/generate-grok-baseline`  
4. Ingest challengers → same evaluate endpoint  
5. `GET /api/bounties/{id}/beat-grok` → champion + vectors  
6. Optional: Publish **BEAT GROK** post to X when OAuth configured  

---

## New / extended API

| Method | Path | Purpose |
| ------ | ---- | ------- |
| POST | `/api/bounties` | `mode=beat_grok` or `optimize` |
| POST | `/api/bounties/{id}/generate-grok-baseline` | Real Grok Build → freeze |
| GET | `/api/bounties/{id}/beat-grok` | Champion verdict + comparison |

---

## Credentials

### Grok Build (baseline generation)

- Local: `grok` CLI authenticated (already works headless here), **or**
- `XAI_API_KEY` in `.env` from https://console.x.ai  

### X OAuth (publish / sign-in)

```env
X_CLIENT_ID=
X_CLIENT_SECRET=
X_OAUTH_CALLBACK_URL=http://localhost:3000/api/auth/x/callback
```

Scopes: `tweet.read tweet.write users.read offline.access media.write`

### X Money

**Unavailable** — no public developer API. Do not fake settlement.

---

## Security notes

- OAuth tokens encrypted at rest  
- Grok and humans share the evaluator  
- Evaluation vectors stored (functionality / performance / integrity)  
- Production hardening remaining: KMS, hardened sandbox, webhook mTLS  

---

## License

Hackathon prototype — use at your own risk.
