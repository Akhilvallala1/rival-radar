import json
import logging
from collections import defaultdict

from langchain_anthropic import ChatAnthropic
from slack_sdk.webhook import WebhookClient

from rival_radar.config import settings
from rival_radar.database import SessionLocal
from rival_radar.models import CompetitorAlert
from rival_radar.state import MonitorState

logger = logging.getLogger(__name__)

_llm = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=1024)

_SYSTEM = (
    "You are a competitive intelligence analyst for a B2B SaaS company. "
    "Given changes detected on a competitor's web pages, write a concise 2-4 sentence analysis "
    "explaining what changed and what it signals strategically. "
    "Be specific. Focus on what matters to a product manager or founder. "
    "When G2 review data is present, note any rating changes (even 0.1 stars is significant at "
    "scale), large swings in review volume, and recurring themes in the newest review snippets "
    "that signal customer sentiment shifts."
)


def _format_g2_diff(g2_changes: list[dict]) -> str:
    lines = []
    for c in g2_changes:
        try:
            old = json.loads(c["old"]) if c["old"] else {}
            new = json.loads(c["new"]) if c["new"] else {}
        except json.JSONDecodeError:
            old, new = {}, {}
        recent = "\n".join(
            f"  • {r['title']}: {r['snippet']}"
            for r in new.get("recent_reviews", [])
        )
        lines.append(
            f"Overall rating:  {old.get('overall_rating', 'N/A')} → "
            f"{new.get('overall_rating', 'N/A')}\n"
            f"Review count:    {old.get('review_count', 'N/A')} → "
            f"{new.get('review_count', 'N/A')}\n"
            f"Recent reviews (new):\n{recent}"
        )
    return "\n\n".join(lines)


def _send_keyword_alert(
    keyword: str,
    competitor_name: str,
    url: str,
    new_excerpt: str,
    webhook_url: str,
) -> None:
    client = WebhookClient(webhook_url)
    text = (
        f":rotating_light: *Keyword alert* — `{keyword}` detected for *{competitor_name}*\n"
        f"URL: {url}\n"
        f"Excerpt: _{new_excerpt[:300]}_"
    )
    response = client.send(text=text)
    if response.status_code != 200:
        logger.error("Keyword alert Slack send failed: %d", response.status_code)


def _check_keyword_alerts(diffs: dict, competitor_map: dict) -> None:
    """Fire immediate Slack pings for keyword matches before the LLM brief is assembled."""
    if not settings.slack_webhook_url:
        return

    changed_comp_ids = {
        competitor_map[diff["competitor"]]
        for diff in diffs.values()
        if diff.get("changed") and diff["competitor"] in competitor_map
    }
    if not changed_comp_ids:
        return

    with SessionLocal() as db:
        alerts = (
            db.query(CompetitorAlert)
            .filter(CompetitorAlert.competitor_id.in_(changed_comp_ids))
            .all()
        )

    if not alerts:
        return

    alerts_by_comp: dict[int, list[CompetitorAlert]] = defaultdict(list)
    for a in alerts:
        alerts_by_comp[a.competitor_id].append(a)

    for url, diff in diffs.items():
        if not diff.get("changed"):
            continue
        comp_name = diff["competitor"]
        comp_id = competitor_map.get(comp_name)
        if comp_id is None:
            continue
        new_excerpt = diff.get("new_excerpt", "").lower()
        for alert in alerts_by_comp.get(comp_id, []):
            if alert.keyword in new_excerpt:
                _send_keyword_alert(
                    keyword=alert.keyword,
                    competitor_name=comp_name,
                    url=url,
                    new_excerpt=diff.get("new_excerpt", ""),
                    webhook_url=settings.slack_webhook_url,
                )


def analyst(state: MonitorState) -> dict:
    diffs = state.get("diffs", {})

    competitor_map = {
        c["name"]: c["competitor_id"]
        for c in state.get("competitors", [])
    }

    _check_keyword_alerts(diffs, competitor_map)

    by_competitor: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"web": [], "g2": []}
    )
    for url, diff in diffs.items():
        if diff.get("changed"):
            source = diff.get("source", "web")
            bucket = "g2" if source == "g2" else "web"
            by_competitor[diff["competitor"]][bucket].append(
                {
                    "url": url,
                    "old": diff.get("old_excerpt", ""),
                    "new": diff.get("new_excerpt", ""),
                }
            )

    analyses: list[str] = []
    for comp_name, buckets in by_competitor.items():
        web_changes = buckets["web"]
        g2_changes = buckets["g2"]

        if not web_changes and not g2_changes:
            continue

        web_text = (
            "\n\n".join(
                f"URL: {c['url']}\nBefore: {c['old'][:300]}\nAfter:  {c['new'][:300]}"
                for c in web_changes
            )
            if web_changes
            else "No website changes detected."
        )
        g2_text = _format_g2_diff(g2_changes) if g2_changes else "No G2 changes detected."

        user_msg = (
            f"Competitor: {comp_name}\n\n"
            f"Website changes detected this week:\n{web_text}\n\n"
            f"G2 review page changes:\n{g2_text}"
        )
        response = _llm.invoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )
        text = response.content if isinstance(response.content, str) else str(response.content)
        analyses.append(f"*{comp_name}*\n{text}")

    return {"analyses": analyses}
