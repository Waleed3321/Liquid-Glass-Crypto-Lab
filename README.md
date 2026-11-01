# Liquid Glass Crypto Lab

A paper-only research desk for **newly created Solana and BNB Chain tokens**.
It discovers pairs younger than six hours, screens them for safety with free and
keyless providers, scores each one 0–100, runs a deliberately conservative
strategy, records simulated fills, and presents everything in a Liquid Glass
Dark dashboard.

> **Nothing here can touch real money.** There are no wallets, no private keys,
> no signing, no deposits or withdrawals, and no swap execution anywhere in this
> repository. Every fill, fee, and slippage number is an estimate labelled as
> such.

- $10 starting paper balance
- Max 3 open positions, max $2.50 per initial entry, $0.50 daily loss cap
- 1% maximum simulated price impact
- Independent 60-second scanner (in-process loop plus an external keep-alive tick)
- 11 dashboard pages, server-sent events live updates, Plotly charts
- Free to deploy: Render web service + Neon Postgres + static dashboard host

---

## Contents

- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Strategy A](#strategy-a--conservative-momentum-pullback)
- [Scoring and security](#scoring-and-security)
- [Risk enforcement](#risk-enforcement)
- [API](#api)
- [Dashboard](#dashboard)
- [Tests](#tests)
- [Scripts](#scripts)
- [Free deployment](#free-deployment)
- [Discord from zero](#discord-from-zero)
- [Limitations of the free tier](#limitations-of-the-free-tier)
- [Security statement](#security-statement)

---

## How it works

```
GeckoTerminal new pools ─┐
DEX Screener enrichment  ├─► snapshot → score → security → Strategy A → paper fills
GoPlus + RugCheck        ┘                                        │
                                                                  └─► SQLite/Postgres
                                                                        │
Dashboard (static) ◄──── FastAPI /api/v1 ◄── SSE stream ◄───────────────┘
Discord ◄──────── notification outbox (retried, never blocks a trade)
```

Layering is strict: `api → services → repositories → models`. Providers, the
scanner, strategies, execution and risk never import FastAPI, and the strategy,
impact, fee, slippage and score cores are pure functions over dataclasses, so
they are unit-tested without a database or network.

```
app/
  api/v1/        health, scanner, tokens, watchlist, portfolio, trades,
                 strategies, analytics, notifications, settings, stream
  core/          config, logging, security, clock, errors, deps
  db/            engine (SQLite/Postgres), session, bootstrap
  models/        tokens, pairs, snapshots, security, scores, watchlist,
                 accounts, positions, orders, fills, decisions, daily
                 performance, scanner runs/lease, notifications, settings
  providers/     geckoterminal, dexscreener, goplus, rugcheck, discord,
                 rate limiter, TTL cache, retry + circuit breaker
  scanner/       tick pipeline, loop, lease, rotation, heartbeat, retention
  services/      market, security, scoring, portfolio, trade, analytics, events
  strategies/    config, indicators, strategy_a, exits, engine
  risk/          locks, limits, guards, daily loss
  execution/     impact, fees, slippage, quote, simulator
  notifications/ dispatcher + templates
frontend/        no-build ES modules, hash router, Liquid Glass Dark CSS
migrations/      Alembic baseline
scripts/         seed, scan_once, smoke_api, verify_deploy, export_static,
                 publish_github, deploy_render
tests/           97 tests, no network access
```

## Quick start

Requirements: [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
uv sync
uv run uvicorn app.main:app --workers 1
```

Open <http://127.0.0.1:8000>. The dashboard is served by FastAPI itself, so no
second server or build step is needed. On first boot the app creates the SQLite
schema and the $10 paper account.

Useful commands:

```bash
uv run pytest -q                      # 106 tests, no network
uv run ruff check app tests scripts
uv run python scripts/seed.py reset   # clearly-labelled DEMO-* tokens
uv run python scripts/scan_once.py    # one scanner tick, prints the result JSON
uv run python scripts/smoke_api.py --base http://127.0.0.1:8000
uv run python scripts/neon_services.py  # probe every Neon service with env vars
npm run build                         # syntax check + export dist/ for a static host
```

The scanner starts with the app and ticks every 60 seconds. Free upstream
providers are rate limited, so keep the interval at 60 s and let the built-in
limiter handle bursts.

## Configuration

Everything is environment driven; `.env.example` documents every key. The most
important ones:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/crypto_lab.db` | runtime URL; Neon's **pooled** string in production |
| `DATABASE_URL_UNPOOLED` | empty | Neon's **direct** string; used by Alembic (falls back to `DATABASE_URL`) |
| `APP_ENV` | `development` | `production` for deployments |
| `SCANNER_ENABLED` | `true` | in-process 60 s loop |
| `SCAN_INTERVAL_SECONDS` | `60` | loop interval |
| `DISCOVERY_WINDOW_HOURS` | `6` | only pairs created inside this window |
| `SCANNER_TICK_TOKEN` | empty | required header for `POST /scanner/tick` |
| `ADMIN_TOKEN` | empty | protects settings and scanner start/stop when set |
| `CORS_ORIGINS` | `*` | comma-separated origins for a separately hosted dashboard |
| `DISCORD_WEBHOOK_URL` | empty | Discord notifications |
| `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` | empty | optional bot transport |
| `INITIAL_BALANCE_USD` | `10` | paper balance created once |
| `SOL_PRICE_USD`, `BNB_PRICE_USD` | `150`, `600` | fee estimates |

Hard risk caps (`MAX_OPEN_POSITIONS`, `MAX_POSITION_USD`,
`DAILY_LOSS_LIMIT_USD`, `MAX_PRICE_IMPACT_PCT`) and the strategy thresholds are
also persisted in the database and editable through the dashboard **within the
documented bounds only** — a user can tighten a limit, never loosen it.

## Strategy A — Conservative Momentum Pullback

Entry, in order (all pure functions in `app/strategies/strategy_a.py`):

1. **Observation** — at least 8 snapshots spanning ≥10 minutes, no gap longer
   than 150 s. Only the newest contiguous run counts, so a scanner restart can
   never borrow data from before the downtime.
2. **Trend** — log-price slope over the last hour between +3% and +40%.
3. **Pullback** — 3–12% below the recent peak.
4. **Stabilisation** — the last candles sit inside a 3% band and stop falling.
5. **Anti-vertical** — rejects 5-minute moves above 15%, price more than 1.15×
   the 10-period SMA, and vertical candles.
6. **Liquidity** — at least $8,000 pooled and no 30% deterioration.
7. **Activity** — buy/sell ratio between 1.1 and 4.0, turnover above 5%.
8. **Quality gates** — score ≥62, confidence ≥0.6, signal strength ≥0.55,
   security eligible with no missing critical field.
9. **Cost** — round-trip estimate under 3%.
10. **Sizing** — `min($2.50, cash)`; below $1.00 the setup is skipped (`NO_EDGE`).

Exits, first match wins:

| Rule | Default |
| --- | --- |
| Stop loss | −18% |
| Security breakdown | any critical field turns FAIL/UNAVAILABLE |
| Liquidity collapse | pooled liquidity below 50% of entry |
| Momentum breakdown | 5-minute drop beyond 8% |
| Trailing stop | 12% below peak, armed after +30% |
| Take profit | sell half at +50%, remainder at +100% |

Every exit carries a stable idempotency key (`pos{id}:{rule}`), so a scanner
retry can never double-sell.

## Scoring and security

The 0–100 opportunity score weights liquidity 25, volume 20, activity 15,
holder distribution 15, momentum quality 15 (spike-penalised) and security
completeness 10. It also returns `security_risk`, `data_confidence` (discounted
by staleness), `signal_strength`, per-component explanations and rejection
codes. Rejected candidates are stored too, which is what the Market Intelligence
page charts.

Security normalises honeypot flags, buy/sell tax, mint/freeze authority,
ownership, LP lock, holder concentration and liquidity into
`PASS / WARNING / FAIL / UNKNOWN / UNAVAILABLE`, always with the provider and raw
value attached. **Missing data is never treated as safe**: any critical field
that is unknown or unavailable blocks automatic entry.

## Risk enforcement

A single path (`app/risk/locks.py::risk_transaction`) owns every write:

- Postgres: `pg_advisory_xact_lock` plus `SELECT … FOR UPDATE` on the account.
- SQLite: one process-wide `asyncio.Lock` plus `BEGIN IMMEDIATE` (WAL,
  `busy_timeout=8000`); run uvicorn with `--workers 1`.

Inside the transaction, in this order: idempotency (`client_order_id` /
`exit_key`), open-position count, notional cap, cash, daily loss, then
quote/impact/staleness/security gates. Any failure rolls the whole transaction
back. Daily loss is stored per `(account, trading_day)` so a restart cannot reset
the loss budget.

Stable error codes include `MAX_POSITIONS`, `POSITION_SIZE`,
`DAILY_LOSS_LIMIT`, `IMPACT_LIMIT`, `STALE_DATA`, `SECURITY_REJECTED`,
`SECURITY_INCOMPLETE`, `DUPLICATE_ORDER` and `COOLDOWN_ACTIVE`.

## API

All endpoints live under `/api/v1`; interactive docs at `/api/docs`.

| Area | Endpoints |
| --- | --- |
| Health | `GET /health` |
| Scanner | `GET /scanner/status`, `GET /scanner/runs`, `POST /scanner/start`, `POST /scanner/stop`, `POST /scanner/tick` |
| Tokens | `GET /tokens`, `GET /tokens/{id}`, `GET /tokens/{id}/history`, `POST/DELETE /tokens/{id}/watchlist` |
| Watchlist | `GET /watchlist` |
| Portfolio | `GET /portfolio`, `GET /portfolio/positions`, `GET /portfolio/performance`, `GET /portfolio/equity` |
| Paper trades | `POST /paper-trades/buy`, `POST /paper-trades/sell`, `GET /paper-trades/history` |
| Strategy | `GET /strategies`, `PUT /strategies/settings`, `POST /strategies/settings/reset`, `GET /strategies/decisions`, `GET /strategies/limits` |
| Analytics | `GET /analytics`, `GET /analytics/market`, `GET /analytics/portfolio` |
| Notifications | `GET /notifications`, `POST /notifications/test`, `POST /notifications/dispatch` |
| Settings | `GET /settings`, `PUT /settings` |
| Stream | `GET /stream` (SSE: `status`, `heartbeat`, `scanner`, `trade`, `watchlist`, `notifications`, `portfolio`) |

Errors always use one shape:

```json
{"error": {"code": "MAX_POSITIONS", "message": "…", "details": {}, "request_id": "…"}}
```

## Dashboard

Eleven pages: Overview, Live Scanner, Watchlist, Paper Portfolio, Open Positions,
Trade History, Strategy Lab, Market Intelligence, Notifications, Settings and
Token Details. Vanilla HTML/CSS/ES modules with a hash router — no build step,
no framework, no CDN. Secrets are masked server-side; the Settings page keeps an
optional admin token in `sessionStorage` only.

`frontend/config.js` sets `apiBase`. Leave it empty when FastAPI serves the
dashboard; set it to the API origin when the dashboard is hosted statically.

## Tests

```bash
uv run pytest -q
```

The suite runs without network access using fake providers over
`httpx.MockTransport` and a temporary SQLite database per test. It covers the
required behaviours end to end — $10 start, 3-position cap, $2.50 cap, daily
loss and rollover, fees, slippage, impact boundary, exact-half partial exit,
full exit, realised/unrealised P&L, duplicate orders, stale data, security
failure, missing security, restart and lease recovery, rate limits and circuit
breaking, Discord failure isolation, persistence across restart, and 20
concurrent buys that must end with ≤3 positions and non-negative cash — plus
strategy, scoring, exit-engine, API-contract and logging-contract suites.

## Scripts

| Script | What it does |
| --- | --- |
| `scripts/seed.py reset\|list\|refresh\|bump` | Demo `DEMO-*` tokens for local acceptance (never real market data) |
| `scripts/scan_once.py` | Run exactly one scanner tick and print the result |
| `scripts/smoke_api.py` | Read-only endpoint smoke test against any base URL |
| `scripts/verify_deploy.py` | Live acceptance checklist (health, cadence, caps, discovery, SSE, rejections, secrets) |
| `scripts/export_static.py` | Build `dist/` for a static host with `apiBase` injected |
| `scripts/publish_github.py` | Create the public repo and push (token from env only) |
| `scripts/deploy_render.py` | Create/update the Render service from env variables |

## Free deployment

The whole stack is free and cloud-hosted; after deployment nothing depends on
your PC.

```
Browser → static dashboard (Qoder Sites or any static host)
              → Render free web service (Docker, one uvicorn worker)
                    → Neon free Postgres + Discord webhook
Keep-alive (cloud only):
   UptimeRobot free 5-min HTTP monitor → GET /api/v1/health
   GitHub Actions schedule */5        → GET /api/v1/health + POST /api/v1/scanner/tick
   in-process asyncio loop           → scan every 60 s while awake
```

### 1. GitHub

```bash
export GITHUB_TOKEN=...        # or put it in .deploy.env (git-ignored)
uv run python scripts/publish_github.py --dry-run
uv run python scripts/publish_github.py
```

The script creates a public repository, commits, and pushes without ever
printing or storing the token.

### 2. Neon Postgres

The project is already linked to a Neon project (`neon.ts` + `neon deploy`).

1. `neon deploy` provisions the declared services and writes `.env.local`
   (`DATABASE_URL`, `DATABASE_URL_UNPOOLED`, the function URL, Neon Auth JWKS,
   Realtime URL/secret and the S3 credentials).
2. Migrate with `alembic upgrade head`. Alembic uses the **direct** endpoint
   (`DATABASE_URL_UNPOOLED`); PgBouncer cannot host DDL sessions.
3. The app uses the **pooled** endpoint at runtime. `app/core/config.py` rewrites
   provider URLs for asyncpg (drops `channel_binding`/`sslmode`, adds
   `ssl=require`) and disables the prepared-statement cache on `-pooler` hosts.
4. Check every service with `python scripts/neon_services.py`.

Only Postgres is consumed by request paths. The app is a single-user paper lab
with its own SSE stream, no sign-in, no uploads and no serverless functions, so
Auth, Object Storage, Functions and Realtime are verified at the service level
rather than wired into code that would never use them.

### 3. Render

Either import this repository as a **Blueprint** (it contains `render.yaml`) or
run:

```bash
export RENDER_API_KEY=...
export GITHUB_REPO=owner/liquid-glass-crypto-lab
export DATABASE_URL='postgresql://…?sslmode=require'
export DISCORD_WEBHOOK_URL=...   # optional
export CORS_ORIGINS=https://your-dashboard-host
uv run python scripts/deploy_render.py
```

The script creates one free Docker web service (`--workers 1`), injects the env
variables, waits for the health check and prints the public URL. It never prints
secret values.

Prefer manual setup? In Render: **New → Web Service → Docker**, health check path
`/api/v1/health`, plan *Free*, region *Oregon*, then add the env variables from
`.env.example`. Do not raise the worker count: the in-process risk lock assumes a
single process.

### 4. Keep-alive and external ticks

- **UptimeRobot** (free): HTTP(s) monitor every 5 minutes on
  `https://<service>.onrender.com/api/v1/health`.
- **GitHub Actions**: `.github/workflows/keepalive.yml` runs every 5 minutes.
  Add repository secrets `API_BASE_URL` and `SCANNER_TICK_TOKEN` (Render
  generates the latter; copy it from the service env).

Together they stop the free instance from sleeping and guarantee a tick even if
the internal loop was paused.

### 5. Dashboard

If you host the dashboard separately (for example on Qoder Sites):

```bash
uv run python scripts/export_static.py --api-base https://<service>.onrender.com
```

Publish the generated `dist/` folder with the static host, then set
`CORS_ORIGINS` on Render to that origin and redeploy.

### 6. Verify

```bash
uv run python scripts/verify_deploy.py --base https://<service>.onrender.com
```

The verifier checks health, database, paper-only flag, scanner cadence, the $10
account, hard caps, six-hour discovery on both chains, the SSE heartbeat, an
oversize-order rejection and that no secret leaked into the served frontend. It
exits non-zero on any failure.

## Discord from zero

**Webhook (simplest, no bot):**

1. Discord → your server → *Server Settings → Integrations → Webhooks → New
   Webhook*, pick a channel, copy the URL.
2. Set `DISCORD_WEBHOOK_URL` in Render (never in the repo, never in frontend
   code) and redeploy.
3. The Notifications page shows transport state; use **Send test** to confirm.
   If delivery fails, alerts stay in the outbox as `SKIPPED`/`FAILED` and paper
   trading continues — notifications never block a trade.

**Bot (optional):**

1. <https://discord.com/developers/applications> → *New Application* → *Bot* →
   copy the token → *Reset Token* if it was ever shared.
2. Enable the *Message Content* intent only if you plan to add commands; the lab
   only needs to post messages.
3. Invite the bot to your server with the `bot` scope and *Send Messages*
   permission.
4. Set `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID`, keep `DISCORD_ENABLED=true`,
   redeploy, and send a test from the Notifications page.

## Limitations of the free tier

- **Render free** gives 0.1 CPU / 512 MB. The health-check keep-alive prevents
  the 15-minute sleep, but cold starts after a deploy take ~30–60 s and ticks can
  occasionally be slow. A missed tick is retried on the next one; nothing is
  skipped by design.
- **750 instance-hours/month** covers a single always-on service (~730 h). This
  project deliberately uses exactly one web service.
- **Neon free** is 0.5 GB. Snapshots older than 24 h are downsampled to hourly
  and rows older than 7 days are pruned.
- If the external keep-alive lapses, Render sleeps after 15 minutes and scanning
  pauses until the next request. The dashboard shows scanner staleness, so this
  is visible rather than silent.
- Free provider APIs are rate limited (GeckoTerminal 30 req/min, DEX Screener 60,
  GoPlus, RugCheck). The scanner budgets below those limits, caches responses,
  retries with backoff and degrades a tick instead of failing it.
- The 1% impact rejection is enforced in the quote and risk layers, but with a
  $2.50 cap and the $8,000 liquidity floor no realistic order can reach it; the
  boundary is covered by unit tests rather than a live order.

## Security statement

- Paper trading only. There is no wallet code, no signing, no swaps, no deposits
  and no withdrawal path in this repository.
- Secrets live in environment variables (`.env` locally, service env in the
  cloud). `.env*` and `.deploy.env` are git-ignored; nothing is baked into the
  frontend bundle.
- Deployment scripts read credentials from the local environment and never echo
  them.
- `ADMIN_TOKEN` protects mutating settings and scanner controls on a public
  deployment. `SCANNER_TICK_TOKEN` protects the external tick endpoint.

MIT licensed.
