import logging

from slack_sdk.webhook import WebhookClient

from rival_radar.config import settings
from rival_radar.state import MonitorState

logger = logging.getLogger(__name__)


def notifier(state: MonitorState) -> dict:
    brief = state.get("brief", "")
    webhook_url = settings.slack_webhook_url

    if not webhook_url:
        logger.info("SLACK_WEBHOOK_URL not set — skipping Slack notification.")
        return {}

    if not brief:
        return {}

    client = WebhookClient(webhook_url)
    response = client.send(text=brief)

    if response.status_code != 200:
        # Log the status code only — do not include response.body, which may
        # contain Slack error detail that could reveal webhook endpoint info.
        logger.error("Slack webhook failed with status %s", response.status_code)
        raise RuntimeError(
            f"Slack webhook failed: {response.status_code}"
        )

    logger.info("Slack digest posted (%d chars).", len(brief))
    return {}
