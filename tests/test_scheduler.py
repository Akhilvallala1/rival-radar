"""Tests for run_competitor: verifies Run status transitions (running → done / failed)."""
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rival_radar.models import Base, Competitor, Run
from rival_radar.scheduler import run_competitor

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(bind=_engine)


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def competitor():
    s = _Session()
    comp = Competitor(name="Test Corp", urls=json.dumps(["https://test.example.com"]), cadence="weekly")
    s.add(comp)
    s.commit()
    comp_id = comp.id
    s.close()
    # Re-fetch in a fresh session so the object is properly attached.
    s2 = _Session()
    fresh = s2.get(Competitor, comp_id)
    s2.close()
    return fresh


@patch("rival_radar.scheduler.SessionLocal", _Session)
@patch("rival_radar.tracing.build_run_config", return_value={})
@patch("rival_radar.graph.app")
def test_run_competitor_creates_run_record(mock_app: MagicMock, _mock_cfg: MagicMock, competitor: Competitor):
    mock_app.invoke.return_value = {"brief": "Test brief"}

    run_competitor(competitor)

    s = _Session()
    run = s.query(Run).filter_by(competitor_id=competitor.id).first()
    s.close()
    assert run is not None


@patch("rival_radar.scheduler.SessionLocal", _Session)
@patch("rival_radar.tracing.build_run_config", return_value={})
@patch("rival_radar.graph.app")
def test_run_competitor_sets_status_done(mock_app: MagicMock, _mock_cfg: MagicMock, competitor: Competitor):
    mock_app.invoke.return_value = {"brief": "Competitor dropped pricing by 20%."}

    run_competitor(competitor)

    s = _Session()
    run = s.query(Run).filter_by(competitor_id=competitor.id).first()
    s.close()
    assert run.status == "done"
    assert run.brief == "Competitor dropped pricing by 20%."
    assert run.finished_at is not None


@patch("rival_radar.scheduler.SessionLocal", _Session)
@patch("rival_radar.tracing.build_run_config", return_value={})
@patch("rival_radar.graph.app")
def test_run_competitor_sets_status_failed_on_exception(
    mock_app: MagicMock, _mock_cfg: MagicMock, competitor: Competitor
):
    mock_app.invoke.side_effect = RuntimeError("LLM unavailable")

    with pytest.raises(RuntimeError, match="LLM unavailable"):
        run_competitor(competitor)

    s = _Session()
    run = s.query(Run).filter_by(competitor_id=competitor.id).first()
    s.close()
    assert run.status == "failed"
    assert run.finished_at is not None


@patch("rival_radar.scheduler.SessionLocal", _Session)
@patch("rival_radar.tracing.build_run_config", return_value={})
@patch("rival_radar.graph.app")
def test_run_competitor_no_brief_stored_as_none(
    mock_app: MagicMock, _mock_cfg: MagicMock, competitor: Competitor
):
    mock_app.invoke.return_value = {"brief": ""}

    run_competitor(competitor)

    s = _Session()
    run = s.query(Run).filter_by(competitor_id=competitor.id).first()
    s.close()
    assert run.status == "done"
    assert run.brief is None
