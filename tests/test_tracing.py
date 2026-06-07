from unittest.mock import MagicMock, patch


@patch("rival_radar.tracing.settings")
def test_get_callback_returns_none_when_keys_missing(mock_settings: MagicMock) -> None:
    from rival_radar.tracing import get_callback

    mock_settings.langfuse_public_key = ""
    mock_settings.langfuse_secret_key = ""
    assert get_callback() is None


@patch("rival_radar.tracing.settings")
def test_get_callback_returns_none_when_only_public_key(mock_settings: MagicMock) -> None:
    from rival_radar.tracing import get_callback

    mock_settings.langfuse_public_key = "pk-lf-test"
    mock_settings.langfuse_secret_key = ""
    assert get_callback() is None


@patch("rival_radar.tracing.settings")
def test_build_run_config_no_tracing(mock_settings: MagicMock) -> None:
    from rival_radar.tracing import build_run_config

    mock_settings.langfuse_public_key = ""
    mock_settings.langfuse_secret_key = ""
    config = build_run_config("test-run")
    assert config == {"run_name": "test-run"}
    assert "callbacks" not in config


def test_build_run_config_with_tracing() -> None:
    from unittest.mock import patch as inner_patch

    mock_handler = MagicMock()
    with inner_patch("rival_radar.tracing.get_callback", return_value=mock_handler):
        from rival_radar.tracing import build_run_config

        config = build_run_config("test-run")

    assert config["run_name"] == "test-run"
    assert mock_handler in config["callbacks"]
