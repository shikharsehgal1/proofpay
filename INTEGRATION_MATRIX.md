# ProofPay — Integration Matrix (verified 2026-08-09)

Workspace was empty (greenfield). Capabilities below were checked against current official docs (`docs.x.ai`, `docs.x.com`) and local tooling (`grok` CLI, Docker, Node 25, Python 3.9, `uv`).

| Capability | Official API/tool exists? | Credentials needed | Intended ProofPay use | Build priority |
| ---------- | ------------------------- | ------------------ | --------------------- | -------------- |
| **Grok API (reasoning)** | **Yes** — `https://api.x.ai/v1` Responses/Chat; model `grok-4.5` | `XAI_API_KEY` from [console.x.ai](https://console.x.ai) | Contract compilation, ranking judgment, natural-language explanations | **P0 — core** |
| **Grok function calling** | **Yes** — client-side tools; model requests call, app executes | `XAI_API_KEY` | Verifier agent tools: `inspect_diff`, `run_benchmark`, `run_hidden_tests`, etc. | **P0 — core** |
| **Grok structured outputs** | **Yes** — `response_format` / JSON Schema / SDK `parse()` | `XAI_API_KEY` | Executable bounty contracts as typed JSON | **P0 — core** |
| **Grok multi-agent** | **No first-party multi-agent product API** — implement as app-orchestrated loops/agents on Grok | `XAI_API_KEY` | Separate compiler / investigator / ranker agent roles | **P0 — app-level** |
| **Grok Code (model)** | **Yes** — `grok-4.5` is the coding model on API | `XAI_API_KEY` | Patch mechanism analysis, adversarial code investigation | **P0 — core** |
| **Grok Build (CLI/TUI)** | **Yes** — installable CLI; powers agentic coding | Local `grok` auth or `XAI_API_KEY` | Inside ProofPay: headless repo understanding of bounty/candidate trees | **P1** |
| **Grok Build headless** | **Yes** — `grok -p "..." --yolo --permission-mode bypassPermissions` | Local `grok` auth and/or `XAI_API_KEY` | **Baseline V0 generation** (first-class contestant) | **P0 — core** |
| **Grok Build ACP** | **Yes** — Agent Client Protocol for IDE/host integration | Local grok install | Optional host embedding; not required for hackathon core | **P2** |
| **Imagine images** | **Yes** — Imagine API / `grok-imagine-image*` | `XAI_API_KEY` | Bounty/winner social cards (aesthetic shell; metrics overlaid deterministically) | **P1** |
| **Imagine video** | **Yes** — Imagine video generation/edit | `XAI_API_KEY` | Optional product explainer; not on critical path | **P3** |
| **Grok Voice** | **Yes** — Voice API (TTS/STT/realtime) | `XAI_API_KEY` | Voice bounty authoring after core loop works | **P3** |
| **X Posts (create/read)** | **Yes** — `POST/GET /2/tweets` | X OAuth2 user token: `tweet.read tweet.write users.read offline.access` | Publish bounty post; store real post IDs; winner announcement | **P0 — core** |
| **X replies / conversation** | **Yes** — create replies (`reply.in_reply_to_tweet_id`); conversation lookup / search | Same + search access per tier | Status replies; resolve GitHub URLs from reply text | **P0 — core** |
| **X Activity (XAA) / webhooks** | **Yes** — modern path; AAA deprecated. Events incl. `post.create`, mentions, DMs. Needs public HTTPS webhook + CRC | X developer app; Bearer/app auth; user OAuth for private events; public webhook URL | Real-time reply → submission detection | **P0 — core** |
| **X Account Activity (legacy)** | **Deprecated** — prefer XAA | Enterprise/pay-per-use historically | Do not build new on AAA | **Skip** |
| **X DMs / X Chat** | **Yes** — legacy DM API (`dm.read`/`dm.write`) + X Chat encrypted stack (separate SDK) | `dm.read dm.write` (+ Chat encryption setup for XChat) | Private hidden-test notes / missing GitHub requests | **P2** |
| **X media upload** | **Yes** — media upload + `media.write` scope | `media.write` + user token | Attach Imagine winner cards to posts | **P1** |
| **X user lookup** | **Yes** — `/2/users/me`, `/2/users/by/...` | `users.read` | Identity binding after OAuth | **P0 — core** |
| **X Money** | **No public developer API / merchant SDK found** in official X developer docs | N/A | Settlement remains `VERIFIED — AWAITING EXTERNAL SETTLEMENT` | **STOP — unavailable** |
| **X Search / public data** | **Yes** — recent search, filtered stream (tier-dependent) | App bearer + tier | Fallback reply discovery if webhooks delayed | **P1** |
| **GitHub public repos** | **Yes** — REST API (unauth rate-limited or `GITHUB_TOKEN`) | Optional `GITHUB_TOKEN` | Resolve PR/branch → immutable SHA; fetch trees | **P0 — core** |

## Hard platform boundaries (do not fake)

### X Money
**X Money is not currently programmatically accessible through a public API available to this project.**

- Attempted: search of `docs.x.com`, X API index, Ads/enterprise surfaces, and public reporting.
- Official product surface for consumer X Money exists as an in-app wallet; **no documented developer transfer/escrow/settlement endpoint**.
- Limitation: **fundamental / product-availability**, not a missing env var.
- ProofPay final settlement state without a payment rail: **`VERIFIED` / `READY_FOR_SETTLEMENT`**.

### Grok multi-agent product
No separate multi-agent orchestration API. ProofPay implements multi-role investigation as **application-orchestrated tool loops** on `grok-4.5` (and optional headless Grok Build processes).

## Local tooling already present

| Tool | Status |
| ---- | ------ |
| Docker | Installed (29.x) — required for real sandbox evaluation |
| Node / npm | v25.9.0 |
| Python | 3.9.6 + `uv` |
| `grok` CLI | Installed at `~/.grok/bin/grok` |
| PostgreSQL / Redis host binaries | Not installed — will run via Docker Compose |
| `XAI_API_KEY` in shell | **Not set** — needed before live Grok calls |
| X OAuth credentials | **Not configured** — needed before live X auth/posts |

## Credential checkpoints (when reached)

### A — xAI
```env
XAI_API_KEY=
```
Obtain: https://console.x.ai → API keys (billing/credits required).

### B — X Developer App (OAuth 2.0)
```env
X_CLIENT_ID=
X_CLIENT_SECRET=
X_BEARER_TOKEN=
X_API_KEY=
X_API_SECRET=
```
Scopes for core: `tweet.read tweet.write users.read offline.access media.write`  
Optional DMs: `dm.read dm.write`  
Callback (local): `http://localhost:3000/api/auth/x/callback`  
Callback (deployed): `https://<your-domain>/api/auth/x/callback`

### C — Public URL (webhooks)
X Activity webhooks require publicly reachable HTTPS + CRC. For hackathon: Cloudflare Tunnel / ngrok / Fly / Railway public URL.

### D — Optional
```env
GITHUB_TOKEN=          # higher GitHub rate limits
DATABASE_URL=          # override compose Postgres
REDIS_URL=
TOKEN_ENCRYPTION_KEY=  # Fernet key for OAuth token at-rest encryption
APP_BASE_URL=
```

## Build order (real product)

1. Persistent DB + domain models  
2. Grok contract compiler (structured output)  
3. Docker sandbox evaluator (real numbers only)  
4. Grok investigator tool loop  
5. X OAuth + real post/reply  
6. X Activity webhook (+ conversation poll fallback using **real** X API)  
7. Proof of Completion + UI  
8. Imagine cards + media upload  
9. Voice (after core)  
10. X Money — **blocked until public API exists**
