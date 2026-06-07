"""Integration test: full LangGraph pipeline with all external I/O mocked."""
from unittest.mock import AsyncMock, MagicMock, patch

from rival_radar.state import DiffEntry, MonitorState


def _make_initial_state() -> MonitorState:
    return MonitorState(
        competitors=[{"competitor_id": 1, "name": "Acme Corp", "urls": ["https://acme.com/pricing"]}],
        diffs={},
        analyses=[],
        brief="",
        run_id=0,
    )


@patch("rival_radar.nodes.notifier.settings")
@patch("rival_radar.nodes.writer._llm")
@patch("rival_radar.nodes.analyst._llm")
@patch("rival_radar.nodes.scraper._scrape_all", new_callable=AsyncMock)
def test_full_pipeline_changed_content(
    mock_scrape: AsyncMock,
    mock_analyst_llm: MagicMock,
    mock_writer_llm: MagicMock,
    mock_notifier_settings: MagicMock,
) -> None:
    from rival_radar.graph import app

    mock_scrape.return_value = {
        "https://acme.com/pricing": DiffEntry(
            competitor="Acme Corp",
            changed=True,
            old_excerpt="Pro plan: $99/month",
            new_excerpt="Pro plan: $79/month",
        )
    }
    mock_analyst_llm.invoke.return_value = MagicMock(
        content="Acme reduced Pro pricing by 20%, likely responding to competitive pressure."
    )
    mock_writer_llm.invoke.return_value = MagicMock(
        content="🎯 *Rival Radar — Weekly Brief*\n\n*Acme Corp* — dropped pricing to $79/month."
    )
    mock_notifier_settings.slack_webhook_url = ""  # skip Slack send

    result = app.invoke(_make_initial_state())

    assert result["brief"] != ""
    assert "Rival Radar" in result["brief"]
    assert len(result["analyses"]) == 1
    assert "Acme Corp" in result["analyses"][0]
    mock_analyst_llm.invoke.assert_called_once()
    mock_writer_llm.invoke.assert_called_once()


@patch("rival_radar.nodes.notifier.settings")
@patch("rival_radar.nodes.writer._llm")
@patch("rival_radar.nodes.analyst._llm")
@patch("rival_radar.nodes.scraper._scrape_all", new_callable=AsyncMock)
def test_full_pipeline_no_changes(
    mock_scrape: AsyncMock,
    mock_analyst_llm: MagicMock,
    mock_writer_llm: MagicMock,
    mock_notifier_settings: MagicMock,
) -> None:
    from rival_radar.graph import app

    mock_scrape.return_value = {
        "https://acme.com/pricing": DiffEntry(
            competitor="Acme Corp",
            changed=False,
            old_excerpt="Pro plan: $99/month",
            new_excerpt="Pro plan: $99/month",
        )
    }
    mock_writer_llm.invoke.return_value = MagicMock(
        content="🎯 *Rival Radar — Weekly Brief*\n\nNo significant changes detected."
    )
    mock_notifier_settings.slack_webhook_url = ""

    result = app.invoke(_make_initial_state())

    # No changes → analyst skips LLM, writer still produces a brief
    mock_analyst_llm.invoke.assert_not_called()
    assert result["analyses"] == []
    assert result["brief"] != ""


@patch("rival_radar.nodes.notifier.WebhookClient")
@patch("rival_radar.nodes.notifier.settings")
@patch("rival_radar.nodes.writer._llm")
@patch("rival_radar.nodes.analyst._llm")
@patch("rival_radar.nodes.scraper._scrape_all", new_callable=AsyncMock)
def test_full_pipeline_posts_to_slack(
    mock_scrape: AsyncMock,
    mock_analyst_llm: MagicMock,
    mock_writer_llm: MagicMock,
    mock_notifier_settings: MagicMock,
    mock_webhook_cls: MagicMock,
) -> None:
    from rival_radar.graph import app

    mock_scrape.return_value = {
        "https://acme.com": DiffEntry(
            competitor="Acme Corp", changed=True, old_excerpt="old", new_excerpt="new"
        )
    }
    mock_analyst_llm.invoke.return_value = MagicMock(content="Analysis text.")
    mock_writer_llm.invoke.return_value = MagicMock(content="🎯 *Rival Radar* Weekly Brief")
    mock_notifier_settings.slack_webhook_url = "https://hooks.slack.com/test"
    mock_client = MagicMock()
    mock_client.send.return_value = MagicMock(status_code=200, body="ok")
    mock_webhook_cls.return_value = mock_client

    app.invoke(_make_initial_state())

    mock_webhook_cls.assert_called_once_with("https://hooks.slack.com/test")
    mock_client.send.assert_called_once()
