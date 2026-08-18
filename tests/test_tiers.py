"""Tests for tier enforcement on POST /competitors."""
import json
from unittest.mock import patch

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rival_radar.api import _make_session_token, app, limiter
from rival_radar.database import get_session
from rival_radar.models import Base, Competitor, User, UserTier

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(bind=_engine)


def _override_session():
    s = _Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client():
    limiter._storage.reset()
    Base.metadata.create_all(bind=_engine)
    app.dependency_overrides[get_session] = _override_session
    with (
        patch("rival_radar.api.init_db"),
        patch("rival_radar.api.start_scheduler"),
        patch("rival_radar.api.stop_scheduler"),
        patch("rival_radar.api.validate_url_safe"),  # SSRF checks tested elsewhere
    ):
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=_engine)


def _make_user(tier: UserTier = UserTier.starter) -> int:
    s = _Session()
    pw = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    user = User(email="user@test.com", password_hash=pw, tier=tier)
    s.add(user)
    s.commit()
    s.refresh(user)
    uid = user.id
    s.close()
    return uid


def _seed_competitors(user_id: int, count: int) -> None:
    s = _Session()
    for i in range(count):
        s.add(Competitor(
            user_id=user_id,
            name=f"Comp{i}",
            urls=json.dumps([f"https://comp{i}.example.com"]),
            cadence="weekly",
        ))
    s.commit()
    s.close()


def test_starter_cannot_exceed_two_competitors(client: TestClient):
    uid = _make_user(UserTier.starter)
    _seed_competitors(uid, 2)
    token = _make_session_token(uid)
    resp = client.post(
        "/competitors",
        json={"name": "Comp3", "urls": ["https://comp3.example.com"], "cadence": "weekly"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 403
    assert "tier_limit_exceeded" in str(resp.json())


def test_starter_can_add_up_to_two_competitors(client: TestClient):
    uid = _make_user(UserTier.starter)
    token = _make_session_token(uid)
    for i in range(2):
        resp = client.post(
            "/competitors",
            json={"name": f"C{i}", "urls": [f"https://c{i}.example.com"], "cadence": "weekly"},
            cookies={"rr_session": token},
        )
        assert resp.status_code == 201


def test_starter_cannot_use_daily_cadence(client: TestClient):
    uid = _make_user(UserTier.starter)
    token = _make_session_token(uid)
    resp = client.post(
        "/competitors",
        json={"name": "Daily", "urls": ["https://daily.example.com"], "cadence": "daily"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 403
    assert "cadence_not_allowed" in str(resp.json())


def test_pro_can_use_daily_cadence(client: TestClient):
    uid = _make_user(UserTier.pro)
    token = _make_session_token(uid)
    resp = client.post(
        "/competitors",
        json={"name": "DailyPro", "urls": ["https://dailypro.example.com"], "cadence": "daily"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 201


def test_team_can_use_hourly_cadence(client: TestClient):
    uid = _make_user(UserTier.team)
    token = _make_session_token(uid)
    resp = client.post(
        "/competitors",
        json={"name": "Hourly", "urls": ["https://hourly.example.com"], "cadence": "hourly"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 201


def test_pro_cannot_exceed_ten_competitors(client: TestClient):
    uid = _make_user(UserTier.pro)
    _seed_competitors(uid, 10)
    token = _make_session_token(uid)
    resp = client.post(
        "/competitors",
        json={"name": "Eleventh", "urls": ["https://eleven.example.com"], "cadence": "weekly"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 403
    assert "tier_limit_exceeded" in str(resp.json())


def test_admin_api_key_bypasses_tier_limits(client: TestClient):
    for i in range(5):
        resp = client.post(
            "/competitors",
            json={"name": f"C{i}", "urls": [f"https://c{i}.example.com"], "cadence": "hourly"},
            headers={"X-API-Key": "changeme"},
        )
        assert resp.status_code == 201


def test_new_user_defaults_to_starter_tier(client: TestClient):
    s = _Session()
    pw = bcrypt.hashpw(b"pass12345", bcrypt.gensalt()).decode()
    user = User(email="default@test.com", password_hash=pw)
    s.add(user)
    s.commit()
    s.refresh(user)
    assert user.tier == UserTier.starter
    s.close()


def test_tier_error_response_contains_message(client: TestClient):
    uid = _make_user(UserTier.starter)
    _seed_competitors(uid, 2)
    token = _make_session_token(uid)
    resp = client.post(
        "/competitors",
        json={"name": "X", "urls": ["https://x.example.com"], "cadence": "weekly"},
        cookies={"rr_session": token},
    )
    body = resp.json()
    assert "message" in body["detail"]
    assert "starter" in body["detail"]["message"]
