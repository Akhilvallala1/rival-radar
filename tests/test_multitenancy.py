"""Multi-tenancy isolation: verify users can only see/modify their own data."""
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
from rival_radar.models import Base, Competitor, Run, User

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
    ):
        with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
            yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def seeded(client: TestClient):
    """Two users, one competitor each, one completed run each."""
    pw = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
    s = _Session()
    u1 = User(email="alice@test.com", password_hash=pw)
    u2 = User(email="bob@test.com", password_hash=pw)
    s.add_all([u1, u2])
    s.commit()
    s.refresh(u1)
    s.refresh(u2)

    c1 = Competitor(user_id=u1.id, name="AliceCorp", urls=json.dumps(["https://alice.example.com"]), cadence="weekly")
    c2 = Competitor(user_id=u2.id, name="BobCorp", urls=json.dumps(["https://bob.example.com"]), cadence="weekly")
    s.add_all([c1, c2])
    s.commit()
    s.refresh(c1)
    s.refresh(c2)

    # Capture IDs now — sqlalchemy expires attributes on the next commit.
    u1_id, u2_id, c1_id, c2_id = u1.id, u2.id, c1.id, c2.id

    r1 = Run(competitor_id=c1_id, status="done", brief="Alice brief")
    r2 = Run(competitor_id=c2_id, status="done", brief="Bob brief")
    s.add_all([r1, r2])
    s.commit()
    s.close()

    return {"u1": u1_id, "u2": u2_id, "c1": c1_id, "c2": c2_id}


# ── /competitors ──────────────────────────────────────────────────────────────


def test_list_competitors_only_own(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["u1"])
    resp = client.get("/competitors", cookies={"rr_session": token})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert "AliceCorp" in names
    assert "BobCorp" not in names


def test_delete_own_competitor_succeeds(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["u1"])
    resp = client.delete(f"/competitors/{seeded['c1']}", cookies={"rr_session": token})
    assert resp.status_code == 204


def test_delete_other_users_competitor_returns_404(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["u1"])
    resp = client.delete(f"/competitors/{seeded['c2']}", cookies={"rr_session": token})
    assert resp.status_code == 404


def test_run_other_users_competitor_returns_404(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["u1"])
    resp = client.post(f"/competitors/{seeded['c2']}/run", cookies={"rr_session": token})
    assert resp.status_code == 404


# ── /runs ─────────────────────────────────────────────────────────────────────


def test_list_runs_only_own(client: TestClient, seeded: dict):
    token = _make_session_token(seeded["u1"])
    resp = client.get("/runs", cookies={"rr_session": token})
    assert resp.status_code == 200
    names = {r["competitor_name"] for r in resp.json()}
    assert "AliceCorp" in names
    assert "BobCorp" not in names


def test_admin_api_key_sees_all(client: TestClient, seeded: dict):
    resp = client.get("/competitors", headers={"X-API-Key": "changeme"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert "AliceCorp" in names
    assert "BobCorp" in names


def test_admin_api_key_sees_all_runs(client: TestClient, seeded: dict):
    resp = client.get("/runs", headers={"X-API-Key": "changeme"})
    assert resp.status_code == 200
    names = {r["competitor_name"] for r in resp.json()}
    assert "AliceCorp" in names
    assert "BobCorp" in names
