from slack_sdk.webhook import WebhookClient

from rival_radar.config import settings
from rival_radar.state import MonitorState


def notifier(state: MonitorState) -> dict:
    brief = state.get("brief", "")
    webhook_url = settings.slack_webhook_url

    if not webhook_url:
        print("[notifier] SLACK_WEBHOOK_URL not set — skipping.")
        return {}

    if not brief:
        return {}

    client = WebhookClient(webhook_url)
    response = client.send(text=brief)

    if response.status_code != 200:
        raise RuntimeError(
            f"Slack webhook failed: {response.status_code} — {response.body}"
        )

    print(f"[notifier] Slack digest posted ({len(brief)} chars).")
    return {}
