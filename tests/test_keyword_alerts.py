"""Tests for keyword alert CRUD endpoints."""
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
from rival_radar.models import Base, Competitor, User

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
        patch("rival_radar.api.validate_url_safe"),
    ):
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def seeded(client: TestClient):
    pw = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    s = _Session()
    user = User(email="user@test.com", password_hash=pw)
    s.add(user)
    s.commit()
    s.refresh(user)
    uid = user.id
    comp = Competitor(
        user_id=uid,
        name="TestCorp",
        urls=json.dumps(["https://testcorp.example.com"]),
        cadence="weekly",
    )
    s.add(comp)
    s.commit()
    s.refresh(comp)
    cid = comp.id
    s.close()
    return {"uid": uid, "cid": cid}


def test_create_alert_returns_201(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["uid"])
    resp = client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "pricing"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["keyword"] == "pricing"
    assert body["competitor_id"] == seeded["cid"]
    assert "id" in body
    assert "created_at" in body


def test_create_alert_normalises_keyword_to_lowercase(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["uid"])
    resp = client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "PRICING"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 201
    assert resp.json()["keyword"] == "pricing"


def test_create_alert_duplicate_returns_409(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["uid"])
    client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "pricing"},
        cookies={"rr_session": token},
    )
    resp = client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "pricing"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 409


def test_create_alert_nonexistent_competitor_returns_404(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["uid"])
    resp = client.post(
        "/competitors/9999/alerts",
        json={"keyword": "pricing"},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 404


def test_list_alerts_returns_all_keywords(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["uid"])
    for kw in ["pricing", "enterprise", "roadmap"]:
        client.post(
            f"/competitors/{seeded['cid']}/alerts",
            json={"keyword": kw},
            cookies={"rr_session": token},
        )
    resp = client.get(
        f"/competitors/{seeded['cid']}/alerts",
        cookies={"rr_session": token},
    )
    assert resp.status_code == 200
    keywords = {a["keyword"] for a in resp.json()}
    assert keywords == {"pricing", "enterprise", "roadmap"}


def test_delete_alert_returns_204(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["uid"])
    resp = client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "pricing"},
        cookies={"rr_session": token},
    )
    alert_id = resp.json()["id"]
    resp = client.delete(f"/alerts/{alert_id}", cookies={"rr_session": token})
    assert resp.status_code == 204


def test_delete_alert_removes_from_list(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["uid"])
    resp = client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "pricing"},
        cookies={"rr_session": token},
    )
    alert_id = resp.json()["id"]
    client.delete(f"/alerts/{alert_id}", cookies={"rr_session": token})
    resp = client.get(
        f"/competitors/{seeded['cid']}/alerts",
        cookies={"rr_session": token},
    )
    assert resp.json() == []


def test_delete_other_users_alert_returns_404(client: TestClient, seeded: dict):
    pw = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    s = _Session()
    user2 = User(email="user2@test.com", password_hash=pw)
    s.add(user2)
    s.commit()
    s.refresh(user2)
    uid2 = user2.id
    s.close()

    token1 = _make_session_token(seeded["uid"])
    resp = client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "pricing"},
        cookies={"rr_session": token1},
    )
    alert_id = resp.json()["id"]

    token2 = _make_session_token(uid2)
    resp = client.delete(f"/alerts/{alert_id}", cookies={"rr_session": token2})
    assert resp.status_code == 404


def test_alert_endpoints_require_login(client: TestClient, seeded: dict):
    resp = client.post(
        f"/competitors/{seeded['cid']}/alerts",
        json={"keyword": "pricing"},
        headers={"X-API-Key": "changeme"},
    )
    assert resp.status_code == 401
