from unittest.mock import MagicMock, patch

import pytest

from rival_radar.nodes.notifier import notifier
from rival_radar.state import MonitorState


def _make_state(brief: str = "Test weekly brief") -> MonitorState:
    return MonitorState(
        competitors=[],
        diffs={},
        analyses=[],
        brief=brief,
        run_id=0,
    )


@patch("rival_radar.nodes.notifier.settings")
def test_notifier_skips_when_no_webhook(mock_settings: MagicMock) -> None:
    mock_settings.slack_webhook_url = ""
    result = notifier(_make_state())
    assert result == {}


@patch("rival_radar.nodes.notifier.settings")
def test_notifier_skips_when_no_brief(mock_settings: MagicMock) -> None:
    mock_settings.slack_webhook_url = "https://hooks.slack.com/test"
    result = notifier(_make_state(brief=""))
    assert result == {}


@patch("rival_radar.nodes.notifier.WebhookClient")
@patch("rival_radar.nodes.notifier.settings")
def test_notifier_sends_brief_to_slack(
    mock_settings: MagicMock, mock_webhook_cls: MagicMock
) -> None:
    mock_settings.slack_webhook_url = "https://hooks.slack.com/test"
    mock_client = MagicMock()
    mock_client.send.return_value = MagicMock(status_code=200, body="ok")
    mock_webhook_cls.return_value = mock_client

    result = notifier(_make_state("🎯 *Rival Radar* weekly brief"))

    mock_webhook_cls.assert_called_once_with("https://hooks.slack.com/test")
    mock_client.send.assert_called_once_with(text="🎯 *Rival Radar* weekly brief")
    assert result == {}


@patch("rival_radar.nodes.notifier.WebhookClient")
@patch("rival_radar.nodes.notifier.settings")
def test_notifier_raises_on_slack_error(
    mock_settings: MagicMock, mock_webhook_cls: MagicMock
) -> None:
    mock_settings.slack_webhook_url = "https://hooks.slack.com/test"
    mock_client = MagicMock()
    mock_client.send.return_value = MagicMock(status_code=400, body="invalid_payload")
    mock_webhook_cls.return_value = mock_client

    with pytest.raises(RuntimeError, match="Slack webhook failed"):
        notifier(_make_state())
