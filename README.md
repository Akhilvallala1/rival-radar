# Rival Radar

[![CI](https://github.com/Akhilvallala1/rival-radar/actions/workflows/ci.yml/badge.svg)](https://github.com/Akhilvallala1/rival-radar/actions/workflows/ci.yml)
[![Deploy](https://github.com/Akhilvallala1/rival-radar/actions/workflows/deploy.yml/badge.svg)](https://github.com/Akhilvallala1/rival-radar/actions/workflows/deploy.yml)

**Live:** https://rival-radar-247626835860.us-central1.run.app  
**API docs:** https://rival-radar-247626835860.us-central1.run.app/docs

Automated competitive intelligence for B2B SaaS teams. Track competitor websites,
pricing pages, blogs, and G2 reviews — get a Slack digest every week summarizing
what changed and what it signals.

## How it works

```
Weekly cron → scraper → analyst → writer → Slack digest
```

- **scraper** — fetches competitor pages, detects content changes vs last run
- **analyst** — Claude interprets what each change signals
- **writer** — Claude synthesizes a Slack-ready weekly brief
- **notifier** — posts the brief to your Slack channel

## Quickstart

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY and SLACK_WEBHOOK_URL
pip install -e ".[dev]"

# scrape a competitor URL and see the diff
python -m rival_radar scrape --url https://competitor.com --name "Acme Corp"
```

## API

```bash
uvicorn rival_radar.api:app --reload
curl http://localhost:8000/health
```

## Development

```bash
ruff check src/ tests/
mypy src/
pytest tests/ -v
```

## Pricing (SaaS)

| Tier | Price | Competitors | Cadence |
|------|-------|-------------|---------|
| Starter | Free | 2 | Weekly |
| Pro | $99/mo | 10 | Daily |
| Team | $299/mo | Unlimited | Hourly |
