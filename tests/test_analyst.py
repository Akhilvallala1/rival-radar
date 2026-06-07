from unittest.mock import MagicMock, patch

from rival_radar.nodes.analyst import analyst
from rival_radar.state import DiffEntry, MonitorState


def _make_state(diffs: dict | None = None) -> MonitorState:
    return MonitorState(
        competitors=[],
        diffs=diffs or {},
        analyses=[],
        brief="",
        run_id=0,
    )


@patch("rival_radar.nodes.analyst._llm")
def test_analyst_skips_unchanged_diffs(mock_llm: MagicMock) -> None:
    state = _make_state(
        diffs={
            "https://acme.com": DiffEntry(
                competitor="Acme", changed=False, old_excerpt="same", new_excerpt="same"
            )
        }
    )
    result = analyst(state)
    mock_llm.invoke.assert_not_called()
    assert result["analyses"] == []


@patch("rival_radar.nodes.analyst._llm")
def test_analyst_returns_analysis_for_changed_url(mock_llm: MagicMock) -> None:
    mock_llm.invoke.return_value = MagicMock(
        content="Acme dropped pricing by 20%, signaling competitive pressure."
    )
    state = _make_state(
        diffs={
            "https://acme.com/pricing": DiffEntry(
                competitor="Acme",
                changed=True,
                old_excerpt="$99/month",
                new_excerpt="$79/month",
            )
        }
    )
    result = analyst(state)
    assert len(result["analyses"]) == 1
    assert "Acme" in result["analyses"][0]
    mock_llm.invoke.assert_called_once()


@patch("rival_radar.nodes.analyst._llm")
def test_analyst_groups_multiple_urls_per_competitor(mock_llm: MagicMock) -> None:
    mock_llm.invoke.return_value = MagicMock(content="Multiple changes detected.")
    state = _make_state(
        diffs={
            "https://acme.com": DiffEntry(
                competitor="Acme", changed=True, old_excerpt="old home", new_excerpt="new home"
            ),
            "https://acme.com/pricing": DiffEntry(
                competitor="Acme", changed=True, old_excerpt="$99", new_excerpt="$79"
            ),
        }
    )
    result = analyst(state)
    # Both URLs belong to same competitor → one LLM call, one analysis
    assert mock_llm.invoke.call_count == 1
    assert len(result["analyses"]) == 1


@patch("rival_radar.nodes.analyst._llm")
def test_analyst_handles_multiple_competitors(mock_llm: MagicMock) -> None:
    mock_llm.invoke.return_value = MagicMock(content="Some analysis.")
    state = _make_state(
        diffs={
            "https://acme.com": DiffEntry(
                competitor="Acme", changed=True, old_excerpt="a", new_excerpt="b"
            ),
            "https://rival.com": DiffEntry(
                competitor="Rival", changed=True, old_excerpt="x", new_excerpt="y"
            ),
        }
    )
    result = analyst(state)
    assert mock_llm.invoke.call_count == 2
    assert len(result["analyses"]) == 2
