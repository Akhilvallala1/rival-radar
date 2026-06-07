# Rival Radar — Product & Build Plan

> **What it is:** Automated competitive intelligence monitor for B2B SaaS teams.
> Track competitor websites, pricing, blogs, and G2 reviews. Detect changes weekly.
> LLM summarizes "what changed and why it matters" → Slack digest.
>
> **Why it sells:** Manually tracking 5 competitors across pricing, blog, reviews, job posts
> takes a PM 3–5 hours/week. Rival Radar does it in seconds for $99/month.
>
> **Resume value:** LangGraph multi-agent ✅ · MCP tools ✅ · Docker/K8s ✅ · LLM observability ✅ · Scheduling ✅ · FastAPI ✅ · Cloud Run ✅
>
> Created: 2026-06-07

---

## Target Customer

**Who:** Product Managers at Series A–B B2B SaaS companies (10–200 employees)
**Pain:** "I need to know when competitors change pricing, launch features, or get bad reviews — before my boss asks me about it."
**Willingness to pay:** $99–299/month (< 1 hour of their time saved weekly)
**How to reach:** LinkedIn cold DM, ProductHunt, SaaS communities (r/SaaS, Indie Hackers)

---

## What Gets Tracked (MVP)

| Source | How | Signal |
|--------|-----|--------|
| Homepage / pricing page | HTTP fetch + hash diff | Messaging/pricing changes |
| Blog RSS feed | feedparser | New posts published |
| G2 reviews | RSS or scrape | New reviews, rating shift |
| Job postings | LinkedIn/Greenhouse RSS | Team growth signals |

---

## Architecture

```
APScheduler (weekly cron)
  └─→ LangGraph pipeline per competitor set:
        START
          → scraper      fetch pages, store snapshot in DB, extract text diff
          → analyst      Claude: "what changed and what does it signal?"
          → writer       Claude: synthesize all competitor changes → Slack brief
          → notifier     POST to Slack webhook
        END
```

### LangGraph State
```python
query: str                  # user's focus ("track pricing and reviews")
competitors: list[str]      # competitor names/URLs
snapshots: dict             # url → previous content hash + text
diffs: dict                 # url → (old_excerpt, new_excerpt)
analyses: list[str]         # per-competitor LLM analysis
brief: str                  # final Slack-formatted digest
run_id: str                 # for Langfuse trace
```

### Data Model (SQLite → Postgres in prod)
```
Competitor(id, name, urls[], slack_webhook, cadence, created_at)
Snapshot(id, competitor_id, url, content_hash, text, scraped_at)
Run(id, competitor_id, started_at, finished_at, brief, status)
```

---

## Tech Stack
Python 3.11 · langgraph · langchain-anthropic · langchain-mcp-adapters ·
fastapi · uvicorn · apscheduler · sqlalchemy · aiohttp · feedparser ·
slack-sdk · langfuse · pydantic-settings · pytest · ruff · mypy ·
Docker · docker-compose · GitHub Actions · Cloud Run

---

## Repo Structure
```
rival-radar/
├── rival_radar_plan.md
├── pyproject.toml
├── .env.example          # ANTHROPIC_API_KEY, SLACK_WEBHOOK_URL, DATABASE_URL
├── README.md
├── src/rival_radar/
│   ├── __init__.py
│   ├── __main__.py       # CLI: python -m rival_radar run --competitor acme.com
│   ├── state.py          # LangGraph MonitorState TypedDict
│   ├── models.py         # SQLAlchemy: Competitor, Snapshot, Run
│   ├── database.py       # engine + session factory
│   ├── graph.py          # LangGraph wiring
│   ├── scheduler.py      # APScheduler weekly jobs
│   ├── tracing.py        # Langfuse callback
│   ├── api.py            # FastAPI: /health, /competitors CRUD, /run
│   └── nodes/
│       ├── __init__.py
│       ├── scraper.py    # fetch pages + RSS, store snapshot, compute diff
│       ├── analyst.py    # Claude: analyze change signals per competitor
│       ├── writer.py     # Claude: write Slack-formatted weekly brief
│       └── notifier.py   # POST brief to Slack webhook
├── tests/
│   ├── __init__.py
│   ├── test_scraper.py   # unit: diff detection (mocked HTTP)
│   └── test_analyst.py   # unit: analyst output shape (mocked LLM)
├── Dockerfile
├── docker-compose.yml    # app + postgres + langfuse
└── .github/workflows/ci.yml
```

---

## Phased Build Plan (~7 weeks at 4 hrs/wk)

**Phase 0 — Scaffold (½ wk):**
Repo, pyproject, ruff/mypy, `.env.example`, DB models (SQLAlchemy), FastAPI `/health`.
✅ `uvicorn` runs, `ruff`/`mypy` pass, DB tables created.

**Phase 1 — Scraper + Diff (1 wk):**
`scraper` node: fetch homepage + pricing page via `aiohttp`, store snapshot in DB,
compute text diff vs last run. `feedparser` for blog RSS.
✅ `python -m rival_radar scrape --url https://acme.com` stores snapshot + prints diff.

**Phase 2 — LangGraph pipeline (1 wk):**
Wire `scraper → analyst → writer → END`. `analyst` node calls Claude per competitor.
`writer` node synthesizes full weekly brief in Slack Block Kit format.
✅ `python -m rival_radar run --competitor acme.com` prints a formatted brief.

**Phase 3 — Slack notifier + scheduler (½ wk):**
`notifier` node POSTs to Slack webhook. APScheduler weekly cron triggers full pipeline.
✅ Running the app posts a real Slack message.

**Phase 4 — Langfuse tracing (½ wk):**
Callback on every node + tool call. Tokens, latency, cost per run visible in Langfuse UI.
✅ Full trace tree visible after a run.

**Phase 5 — FastAPI CRUD + manual trigger (1 wk):**
`POST /competitors` (add), `GET /competitors`, `DELETE /competitors/{id}`,
`POST /competitors/{id}/run` (manual trigger). Pydantic schemas.
✅ Can add a competitor via curl and trigger a run.

**Phase 6 — Tests + Docker (1 wk):**
pytest (scraper unit, analyst unit, 1 integration with mocked Slack).
Dockerfile + docker-compose (app + postgres + langfuse).
✅ `docker compose up` + `pytest` green.

**Phase 7 — CI + Deploy (1 wk):**
GitHub Actions: ruff + mypy + pytest. Cloud Run deploy → live URL.
Landing page (single HTML, Stripe payment link).
✅ Live URL, badge green, landing page with "Start free trial" button.

---

## Monetization Plan

| Tier | Price | Limits | Target |
|------|-------|--------|--------|
| Starter | $0 | 2 competitors, weekly | Lead gen |
| Pro | $99/mo | 10 competitors, daily | Main revenue |
| Team | $299/mo | Unlimited, hourly, API | Upsell |

**GTM:** LinkedIn cold DM to 20 SaaS PMs/week. Offer 30-day free trial.
First 10 paying = $990/mo MRR. Enough for a case study + ProductHunt launch.

---

## Resume Bullet (after deploy)
> Built Rival Radar, a multi-agent competitive intelligence SaaS (LangGraph + Claude + MCP)
> that monitors competitor websites, pricing, and reviews weekly and delivers Slack digests;
> instrumented with Langfuse, containerized with Docker, CI via GitHub Actions, deployed on
> Cloud Run. Acquired first paying customers at $99/month.

---

## Kickoff (Phase 0–1)
Start with:
- pyproject.toml + src layout
- SQLAlchemy models: Competitor, Snapshot, Run
- FastAPI /health
- scraper node: aiohttp fetch → hash → diff → store
- feedparser for RSS
- CLI: `python -m rival_radar scrape --url <url>`
- Unit tests for diff logic
- ruff + mypy + pytest passing
