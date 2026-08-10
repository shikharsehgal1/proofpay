# Grok Reply App Bot

**When someone @mentions the bot on X (or we spot a high-signal opportunity tweet), Grok builds a tiny usable app and replies under that tweet with a live link.**

This is a sibling product surface on the ProofPay monorepo. It reuses X API clients, xAI/Grok, Imagine, and hosting — **not** the bounty escrow flow. Bot credentials are **separate** from any human creator OAuth account.

---

## Product loop

```text
@bot "make a tip calculator for waiters"
        │
        ▼
  Mention ingest (webhook or poll)
        │
        ▼
  Intent + safety (Grok structured)
        │
        ▼
  Generate single-file HTML mini-app (Grok)
        │
        ▼
  Persist + host at /a/{slug}
        │
        ▼
  Optional: Imagine preview screenshot
        │
        ▼
  Reply under original tweet with link (+ media)
```

**Opportunity scan (optional, outbound):**

```text
Curated top accounts  →  recent-search last N hours
        │
        ▼
  Grok scores "would a mini-app help here?"
        │
        ▼
  Queue opportunity jobs (draft / auto if enabled)
        │
        ▼
  Same generate → host → reply pipeline
```

Outbound replies are **off by default** until the new bot account is wired and `REPLY_APP_SCAN_AUTO_REPLY=true`.

---

## Components

| Piece | Location | Role |
| ----- | -------- | ---- |
| Config | `apps/api/app/config.py` | Bot tokens, scan lists, feature flags |
| Models | `ReplyApp`, `ReplyAppJob` | Generated apps + job queue state |
| Intent | `services/reply_app/intent.py` | Parse mention → app brief |
| Generator | `services/reply_app/generator.py` | Grok → self-contained HTML |
| Publisher | `services/reply_app/publisher.py` | Host URL + X reply + media |
| Scanner | `services/reply_app/scanner.py` | Recent tweets from watchlist |
| Pipeline | `services/reply_app/pipeline.py` | End-to-end job runner |
| API | `routes/reply_app.py` | Status, dry-run, poll, scan, serve HTML |
| Web | `apps/web/app/a/[slug]` | Public mini-app shell |
| Webhooks | `routes/webhooks.py` | Mentions also route into bot pipeline |

---

## Auth model (new X account)

Do **not** reuse the ProofPay creator OAuth user.

1. Create a dedicated X app + bot user (e.g. `@GrokReplyApp`).
2. Complete OAuth once for that user (or paste long-lived tokens).
3. Set env:

```bash
REPLY_APP_BOT_ENABLED=true
REPLY_APP_BOT_X_USER_ID=...
REPLY_APP_BOT_X_USERNAME=GrokReplyApp
REPLY_APP_BOT_ACCESS_TOKEN=...          # user context, tweet.write + media.write
REPLY_APP_BOT_ACCESS_TOKEN_SECRET=...  # only if OAuth 1.0a path is used later
# Optional refresh if using OAuth 2.0 rotating tokens:
REPLY_APP_BOT_REFRESH_TOKEN=...

XAI_API_KEY=...                        # required for generation
APP_BASE_URL=https://proofpay-web.fly.dev
```

Mention poll uses the bot user token. App-only bearer can still power recent-search for the opportunity scanner when available.

---

## Ingestion

### A. Mentions (inbound — primary)

1. **Webhook** `POST /api/webhooks/x` — if payload is a mention of the bot, enqueue `ReplyAppJob(source=mention)`.
2. **Poll fallback** `POST /api/reply-app/poll-mentions` — `GET /2/users/:id/mentions` with bot token (works before webhooks are live).

Dedup key: source tweet id (`source_tweet_id` unique).

### B. Opportunity scan (outbound — optional)

`POST /api/reply-app/scan-opportunities`

- Watchlist: `REPLY_APP_SCAN_ACCOUNTS` (comma usernames, no `@`).
- Query shape: `(from:user1 OR from:user2 ...) -is:retweet -is:reply` over recent search.
- Grok scores each tweet: usefulness 0–1, suggested app brief, skip reasons (news-only, pure opinion, already has a link tool, NSFW, etc.).
- Threshold: `REPLY_APP_SCAN_MIN_SCORE` (default `0.72`).
- Creates jobs with `source=opportunity`, `status=draft` unless auto-reply is on.

Default watchlist seeds (editable): product/builder accounts where “I wish I had a tiny tool for this” shows up often — e.g. builders, startup, design, finance tips. Not an endorsement; just a starting set for demos.

---

## Mini-app contract

Grok must return **one self-contained HTML document**:

- Inline CSS + JS (no external build step).
- Mobile-first, dark-friendly, works in mobile X in-app browser.
- No tracking pixels, no exfil of user data.
- No requests to arbitrary third parties except well-known CDNs if unavoidable (prefer zero deps).
- Clear title + one-line purpose in a header.
- Fail closed on unsafe intents (weapons, CSAM, scams, malware, credential harvesting).

Hosted at:

```text
{APP_BASE_URL}/a/{public_slug}
```

API also serves raw HTML at `GET /api/reply-app/apps/{slug}/html` for embedding/debug.

---

## Reply copy

Short, non-spammy:

```text
Built you a quick app for this → {url}
```

Optional Imagine card as attached media when image gen is configured.

---

## Safety & rate limits

| Guard | Default |
| ----- | ------- |
| Max jobs / hour | `REPLY_APP_MAX_JOBS_PER_HOUR=30` |
| Max concurrent generate | 2 (in-process semaphore) |
| Skip self / bot authors | yes |
| Skip if already replied | unique `source_tweet_id` |
| Intent refuse list | scams, malware, adult, weapons, medical diagnosis, etc. |
| Opportunity auto-reply | **off** until explicitly enabled |

---

## API surface

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET | `/api/reply-app/status` | Config readiness (no secrets) |
| POST | `/api/reply-app/dry-run` | Intent + HTML only (no X post) |
| POST | `/api/reply-app/jobs` | Create job from tweet text/id |
| POST | `/api/reply-app/jobs/{id}/run` | Execute pipeline |
| GET | `/api/reply-app/jobs` | List recent jobs |
| GET | `/api/reply-app/apps/{slug}` | App metadata |
| GET | `/api/reply-app/apps/{slug}/html` | Raw HTML |
| POST | `/api/reply-app/poll-mentions` | Pull mentions → jobs |
| POST | `/api/reply-app/scan-opportunities` | Watchlist scan |
| POST | `/api/reply-app/scan-opportunities/run-drafts` | Promote drafts |

---

## Rollout checklist (when new X account is ready)

1. Create bot X user + Developer App with OAuth 2.0 PKCE (scopes: `tweet.read tweet.write users.read offline.access media.write`).
2. Authorize bot user; store access token in Fly secrets (`REPLY_APP_BOT_*`).
3. Set `REPLY_APP_BOT_ENABLED=true`, deploy API + web.
4. `GET /api/reply-app/status` → all green.
5. `POST /api/reply-app/dry-run` with sample text.
6. Enable mention poll cron or webhooks.
7. Run opportunity scan with `auto_reply=false`; review drafts.
8. Flip `REPLY_APP_SCAN_AUTO_REPLY` only after quality looks good.

---

## Non-goals (v1)

- Full multi-page product hosting / auth inside mini-apps
- Replacing ProofPay bounty flow
- Autonomous spam replies at scale
- Guaranteeing X webhook tier availability (poll is first-class)
