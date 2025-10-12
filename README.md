# HS Trends – Help Scout Insights, Dashboard, and Continuous Learning

This repo contains a FastAPI backend and a Next.js dashboard that ingest Help Scout conversations, analyze them (rules + Claude), surface insights, and optionally build a semantic search index in Pinecone. It runs entirely on localhost for development.

## Contents
- api/: FastAPI backend services
- dashboard/: Next.js dashboard (Tailwind v3, Recharts, Lucide)
- worker/: placeholder for future jobs (not required)
- docker-compose.yml: optional compose stack

## What we built

### 1) Dashboard (Next.js)
- Home with links to sections; primary page is `dashboard/pages/dashboard.tsx`.
- Real data only: fetches from the backend; no mock data when live endpoints are present.
- 48h dashboard metrics: trend, categories, platform/severity breakdown, and top clusters.
- Issue Trends Over Time uses hourly UTC buckets with `ts` (ISO) and includes `bugs`, `crashes`, `uxIssues`, `features`, `technical`, `questions`, and `payments` series.
- Insights panel streams Claude-enriched recommendations incrementally:
  - Shows a loading/progress indicator while fetching pages
  - Renders per-message summary, categories, suggested tags, platform/version/level (if found)
  - Links to the real Help Scout conversation (`hs_link`) and the HS API (`api_link`)
  - Newest tickets first (by `number`), with similar-issue counts via `cluster_key`
- Unwanted UI elements (filters/export cards) have been removed per your request.

### 2) Backend (FastAPI)
- SQLite by default for dev (`api/dev.db`). Use Postgres via `DATABASE_URL` or `POSTGRES_*`.
- CORS open for localhost.
- OAuth for Help Scout (optional): `/helpscout/oauth/install`, `/helpscout/oauth/start`, `/helpscout/oauth/callback`, `/helpscout/oauth/status`.
- Webhook endpoint: `/helpscout/webhook` receives HS events, fetches full conversation, classifies, posts to Slack (if configured), and stores a normalized record. Signature check enabled when `HS_WEBHOOK_SECRET` is set.
- Backfill endpoints:
  - `POST/GET /admin/backfill?limit_pages=1` – reads HS conversations and stores them.
  - `GET /admin/backfill_all?max_pages=50` – loops backfill pages (best-effort).
- Conversations/aggregations:
  - `GET /admin/conversations?hours=24&limit=2000`
  - `GET /admin/volume?hours=24&compare=24`
  - `GET /admin/aggregates?hours=24&limit=50`
  - `GET /admin/topic-stats?hours=24`
  - `GET /admin/dashboard?hours=48` – returns ready-to-plot series for the dashboard.
- Insights (rules + Claude):
  - `GET /admin/insights?hours=48&limit=50&page=1&page_size=50&min_number=…`
  - Returns summaries, categories, entities, severity bucket/score, suggested tags, cluster key, HS links, and totals for top categories/keywords.
  - Ordering: newest ticket number first; paging supports incremental loading.
  - Stability: crashes are consistently bucketed as `high`; progress/payment can bump severity.

### 3) LLM Enrichment (Claude)
- File: `api/engine/llm.py` (already wired into endpoints).
- Enable by setting `ANTHROPIC_API_KEY` before starting the API.
- Used to generate concise per-message summaries and extra categories; never writes back to Help Scout.
- **Special Intent Handling**:
  - `incomplete_ticket`: Detects empty tickets (no real user message) → forced to LOW severity
  - `unreadable`: Detects incomprehensible/gibberish messages → forced to LOW severity
  - `delete_account`: Account deletion requests → Slack alert with 🚨 DELETE_REQUEST tag

### 4) Vector DB (Pinecone) – Optional
- Embeddings via OpenAI: `OPENAI_API_KEY` and model `text-embedding-3-small` by default.
- Pinecone index: `PINECONE_API_KEY`, `PINECONE_INDEX` (dimension 1536, metric cosine).
- Endpoints:
  - `POST/GET /admin/reindex_recent?hours=48` – upsert vectors for recent items
  - `POST/GET /admin/reindex_vectors?limit=2000` – bulk upsert all
  - `GET /admin/vector_search?q=…&top_k=10` – semantic search
- Auto-learning:
  - `VECTOR_AUTO=1` upserts a vector for each webhook/backfill item.
  - `VECTOR_BG_REINDEX=1` launches a background thread that periodically reindexes recent updates (cadence via `VECTOR_REINDEX_INTERVAL_MIN`, window via `VECTOR_REINDEX_HOURS`).

## Data model (SQL)
Tables defined in `api/models.py`:
- `hs_conversation` (id, number, subject, last_text, tags, updated_at)
  - Backfill and webhook populate this. `updated_at` uses HS `updatedAt` when available.
- `incident` – cluster rollups and severity buckets (used for Slack threads/alerts)
- `hs_oauth_token` – stores HS OAuth access/refresh tokens and expiry

Embeddings are not stored in SQL; they live in Pinecone.

## Severity policy
- Rule-based score + heuristics (crash, progress loss, payment) → `compute()` in `engine/severity.py`.
- Bucketization:
  - crash => high (consistent)
  - progress_lost => high
  - payment => at least medium
  - **incomplete_ticket** (empty tickets) => **low** (forced override)
  - **unreadable** (gibberish/incomprehensible) => **low** (forced override)
  - otherwise: low/medium/high from score/z-signal

## Slack alerts
- Alerts are sent for new tickets **only if the agent hasn't replied yet** (prevents spam).
- Special intent tags in Slack:
  - 🚨 **DELETE_REQUEST**: Account deletion requests (high priority)
  - 📭 **EMPTY_TICKET**: No real user message provided (low severity)
  - ❓ **UNREADABLE**: Incomprehensible/gibberish content (low severity)
- Configure via: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_DEFAULT_CHANNEL_ID`

## Endpoints – quick reference
- Health: `GET /healthz`
- Webhook: `POST /helpscout/webhook`
- OAuth: `GET /helpscout/oauth/install | /start | /callback | /status`
- Backfill: `GET/POST /admin/backfill?limit_pages=1`, `GET /admin/backfill_all?max_pages=50`
- Conversations: `GET /admin/conversations?hours=24&limit=2000`
- Dashboard data: `GET /admin/dashboard?hours=48`
- Insights: `GET /admin/insights?hours=48&limit=50&page=1&page_size=50&min_number=…`
- Aggregations: `GET /admin/aggregates`, `GET /admin/topic-stats`, `GET /admin/volume`
- Vectors: `GET/POST /admin/reindex_recent`, `GET/POST /admin/reindex_vectors`, `GET /admin/vector_search`

## Local development
### 1) Backend venv
```
cd hs-trends/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional: pip install openai pinecone
ANTHROPIC_API_KEY=… OPENAI_API_KEY=… PINECONE_API_KEY=… PINECONE_INDEX=hs-trends-conversations \
VECTOR_AUTO=1 VECTOR_BG_REINDEX=1 USE_SQLITE=1 uvicorn app:app --reload --port 8080
```

### 2) Dashboard
```
cd hs-trends/dashboard
npm install
npm run dev
# open http://localhost:3000/dashboard
```

### 3) Help Scout OAuth (optional)
- Set `HS_CLIENT_ID`, `HS_CLIENT_SECRET`, `HS_REDIRECT_URL` (your public HTTPS `/helpscout/oauth/callback`).
- Visit `GET /helpscout/oauth/install` to retrieve the authorize URL, or `GET /helpscout/oauth/start` to redirect.
- After consent, `GET /helpscout/oauth/status` should show `connected: true`.

### 4) Backfill
```
# One page
curl 'http://localhost:8080/admin/backfill?limit_pages=1'
# Best-effort many pages
curl 'http://localhost:8080/admin/backfill_all?max_pages=50'
```

### 5) Continuous learning
```
# Recent window upsert
curl 'http://localhost:8080/admin/reindex_recent?hours=48'
# Bulk upsert
curl 'http://localhost:8080/admin/reindex_vectors?limit=2000'
```

### 6) Docker Compose (full stack)
```
cd hs-trends
docker compose up --build
# API → http://localhost:8080/healthz
# Dashboard → http://localhost:3000/dashboard
```

Environment can be supplied via `.env` at the project root; compose uses it for `api`, `dashboard`, and `worker`.

## Environment variables
- Core
  - `USE_SQLITE=1` (default) or `DATABASE_URL`/`POSTGRES_*` for Postgres
  - `VECTOR_AUTO` (0/1), `VECTOR_BG_REINDEX` (0/1), `VECTOR_REINDEX_INTERVAL_MIN`, `VECTOR_REINDEX_HOURS`
- CORS
  - Open by default for localhost via FastAPI `CORSMiddleware`
- Help Scout
  - `HS_API_TOKEN` (PAT) or OAuth: `HS_CLIENT_ID`, `HS_CLIENT_SECRET`, `HS_BASE_URL`, `HS_REDIRECT_URL`
  - Webhook signature: `HS_WEBHOOK_SECRET`
- Slack (optional)
  - `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_DEFAULT_CHANNEL_ID`
- Anthropic (optional)
  - `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- OpenAI embeddings (optional)
  - `OPENAI_API_KEY`, `OPENAI_EMBED_MODEL`, `OPENAI_EMBED_URL`
- Pinecone (optional)
  - `PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_ENV`

## Troubleshooting
- CORS error in browser: usually a backend 500. Check `docker compose logs api` and hit `http://localhost:8080/healthz`. Fix the API error; CORS headers will then be returned.
- Empty graphs: ensure recent data exists. Trigger `GET /admin/backfill?limit_pages=1` and widen `hours`.
- OAuth 401 from Help Scout: verify tokens via `GET /helpscout/oauth/status`; re-run `install`/`start` if needed.
- Pinecone disabled: all vector endpoints return a friendly disabled payload; set API key and index to enable.
- Chrome console error about asynchronous listener: caused by extensions; test in Incognito or another browser.

## License
Proprietary – internal tooling for Help Scout trends and operations.

## Operational notes
- Import warnings in VS Code: `.vscode/settings.json` points the IDE to `api/.venv`.
- Webhook 502 errors usually indicate missing/expired OAuth or signature mismatch.
- Insights pagination lets the UI display results quickly; the dashboard shows progress while loading.
- We do not write LLM outputs back to HS; only read, analyze, and display recommendations.

## Security
- Keep API keys (HS, Anthropic, OpenAI, Pinecone) in your local environment. Do not commit them.
- In production, restrict CORS, add auth on `/admin/*` routes, and rotate keys.

## What to customize next
- Tighten severity scoring and category rules for your product domain.
- Add per-category owners and escalation policies in Slack.
- Extend vector search into a “similar tickets” navigator inside the dashboard.
