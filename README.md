# Rival Radar

[![CI](https://github.com/Akhilvallala1/rival-radar/actions/workflows/ci.yml/badge.svg)](https://github.com/Akhilvallala1/rival-radar/actions/workflows/ci.yml)
[![Deploy](https://github.com/Akhilvallala1/rival-radar/actions/workflows/deploy.yml/badge.svg)](https://github.com/Akhilvallala1/rival-radar/actions/workflows/deploy.yml)

**Live dashboard:** https://rival-radar-247626835860.us-central1.run.app  
**API docs:** https://rival-radar-247626835860.us-central1.run.app/docs

Automated competitive intelligence for B2B SaaS teams. Track competitor websites,
pricing pages, blogs, and G2 reviews — get a Slack digest every week summarizing
what changed and what it signals.

## What it does

Add a competitor URL, click **Run Now**, and within ~60 seconds you get a Claude-generated brief like:

> *🎯 Rival Radar — Weekly Brief | June 07, 2026*
>
> **HubSpot** — Pricing page title tag updated to "Marketing Software Pricing" — a shift
> away from all-in-one CRM framing toward marketing-specific buyers. Suggests possible
> unbundling of their platform narrative. Update battlecards for AEs in competitive deals.

## Architecture

```
HTTP trigger / weekly cron
        │
        ▼
   LangGraph pipeline
   ┌──────────────────────────────────────┐
   │  scraper → analyst → writer → notifier │
   └──────────────────────────────────────┘
        │                    │
   aiohttp + SHA-256    ChatAnthropic
   diff detection       claude-sonnet-4-6
        │                    │
   SQLAlchemy ORM       Slack webhook
   (Postgres/SQLite)
```

- **scraper** — async HTTP fetch, SHA-256 content diff vs last snapshot
- **analyst** — Claude interprets what each change signals competitively
- **writer** — Claude synthesizes a Slack-ready weekly brief with actionable takeaways
- **notifier** — posts the brief to your Slack channel via webhook

## Stack

| Layer | Tech |
|---|---|
| Agent framework | LangGraph |
| LLM | Claude (claude-sonnet-4-6) via langchain-anthropic |
| API | FastAPI + uvicorn |
| Database | SQLAlchemy 2.0 (SQLite dev / Postgres prod) |
| Scheduler | APScheduler (weekly cron, Monday 09:00) |
| Observability | Langfuse tracing |
| CI/CD | GitHub Actions → Google Cloud Run |
| Infra | Docker, GCP Artifact Registry |

## Quickstart

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY and SLACK_WEBHOOK_URL
pip install -e ".[dev]"

# scrape a competitor and see the diff
python -m rival_radar scrape --url https://competitor.com/pricing --name "Acme Corp"

# run the full pipeline once
python -m rival_radar run --competitor-id 1
```

## API

```bash
uvicorn rival_radar.api:app --reload

# health
curl http://localhost:8000/health

# add a competitor
curl -X POST http://localhost:8000/competitors \
  -H "Content-Type: application/json" \
  -d '{"name":"HubSpot","urls":["https://www.hubspot.com/pricing"],"cadence":"weekly"}'

# trigger a run
curl -X POST http://localhost:8000/competitors/1/run

# view recent runs and briefs
curl http://localhost:8000/runs
```

## Development

```bash
ruff check src/ tests/
mypy src/
pytest tests/ -v
```

## Deployment

Pushes to `master` automatically build a Docker image, push to GCP Artifact Registry,
and deploy to Cloud Run via GitHub Actions. Required secrets:

| Secret | Description |
|---|---|
| `GCP_PROJECT_ID` | GCP project ID |
| `GCP_CREDENTIALS` | Service account key JSON |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `DATABASE_URL` | Postgres connection string |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key (optional) |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key (optional) |

## Pricing (SaaS)

| Tier | Price | Competitors | Cadence |
|------|-------|-------------|---------|
| Starter | Free | 2 | Weekly |
| Pro | $99/mo | 10 | Daily |
| Team | $299/mo | Unlimited | Hourly |
