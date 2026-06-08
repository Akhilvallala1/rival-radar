"""Tests for auth routes: signup, login, session tokens, dashboard, logout, API auth."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rival_radar.api import _make_session_token, _verify_session_token, app, limiter
from rival_radar.database import get_session
from rival_radar.models import Base, User

# ── Shared in-memory DB (StaticPool keeps one connection so tables persist) ────
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
    limiter._storage.reset()  # clear rate-limit counters so tests don't bleed into each other
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _signup(
    client: TestClient, email: str = "user@test.com", password: str = "password123"
) -> TestClient:
    client.post("/signup", data={"email": email, "password": password})
    return client


# ── Session token helpers ──────────────────────────────────────────────────────

def test_session_token_roundtrip():
    token = _make_session_token(42)
    assert _verify_session_token(token) == 42


def test_session_token_invalid_string():
    assert _verify_session_token("not-a-valid-token") is None


def test_session_token_empty_string():
    assert _verify_session_token("") is None


# ── /health ────────────────────────────────────────────────────────────────────

def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── GET /signup ────────────────────────────────────────────────────────────────

def test_signup_page_renders(client: TestClient):
    resp = client.get("/signup")
    assert resp.status_code == 200
    assert b"Create account" in resp.content


def test_signup_page_error_short_password(client: TestClient):
    resp = client.get("/signup?error=1")
    assert resp.status_code == 200
    assert b"8 characters" in resp.content


def test_signup_page_error_duplicate(client: TestClient):
    resp = client.get("/signup?error=2")
    assert resp.status_code == 200
    assert b"already exists" in resp.content


# ── POST /signup ───────────────────────────────────────────────────────────────

def test_signup_success_redirects_to_dashboard(client: TestClient):
    resp = client.post("/signup", data={"email": "user@test.com", "password": "password123"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_signup_success_sets_session_cookie(client: TestClient):
    resp = client.post("/signup", data={"email": "user@test.com", "password": "password123"})
    assert "rr_session" in resp.cookies
    assert _verify_session_token(resp.cookies["rr_session"]) is not None


def test_signup_short_password_rejected(client: TestClient):
    resp = client.post("/signup", data={"email": "user@test.com", "password": "short"})
    assert resp.status_code == 303
    assert "error=1" in resp.headers["location"]


def test_signup_duplicate_email_rejected(client: TestClient):
    data = {"email": "dup@test.com", "password": "password123"}
    client.post("/signup", data=data)
    resp = client.post("/signup", data=data)
    assert resp.status_code == 303
    assert "error=2" in resp.headers["location"]


def test_signup_email_stored_lowercase(client: TestClient):
    client.post("/signup", data={"email": "  USER@Test.COM  ", "password": "password123"})
    s = _Session()
    user = s.query(User).filter(User.email == "user@test.com").first()
    s.close()
    assert user is not None


def test_signup_name_optional(client: TestClient):
    resp = client.post("/signup", data={"email": "noname@test.com", "password": "password123"})
    assert resp.status_code == 303


def test_signup_name_stored(client: TestClient):
    client.post(
        "/signup", data={"name": "Akhil", "email": "named@test.com", "password": "pass12345"}
    )
    s = _Session()
    user = s.query(User).filter(User.email == "named@test.com").first()
    s.close()
    assert user is not None
    assert user.name == "Akhil"


# ── GET /login ─────────────────────────────────────────────────────────────────

def test_login_page_renders(client: TestClient):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Sign in" in resp.content


def test_login_page_shows_error(client: TestClient):
    resp = client.get("/login?error=1")
    assert resp.status_code == 200
    assert b"Incorrect" in resp.content


# ── POST /login ────────────────────────────────────────────────────────────────

def test_login_success_redirects_to_dashboard(client: TestClient):
    _signup(client)
    resp = client.post("/login", data={"email": "user@test.com", "password": "password123"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_success_sets_session_cookie(client: TestClient):
    _signup(client)
    resp = client.post("/login", data={"email": "user@test.com", "password": "password123"})
    assert "rr_session" in resp.cookies
    assert _verify_session_token(resp.cookies["rr_session"]) is not None


def test_login_wrong_password_rejected(client: TestClient):
    _signup(client)
    resp = client.post("/login", data={"email": "user@test.com", "password": "wrongpassword"})
    assert resp.status_code == 303
    assert "error=1" in resp.headers["location"]


def test_login_unknown_email_rejected(client: TestClient):
    resp = client.post("/login", data={"email": "ghost@test.com", "password": "password123"})
    assert resp.status_code == 303
    assert "error=1" in resp.headers["location"]


def test_login_case_insensitive_email(client: TestClient):
    _signup(client, email="user@test.com")
    resp = client.post("/login", data={"email": "USER@TEST.COM", "password": "password123"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_google_only_user_cannot_use_password(client: TestClient):
    s = _Session()
    s.add(User(email="google@test.com", google_id="gid123"))
    s.commit()
    s.close()
    resp = client.post("/login", data={"email": "google@test.com", "password": "anypassword"})
    assert resp.status_code == 303
    assert "error=1" in resp.headers["location"]


# ── GET / (dashboard) ──────────────────────────────────────────────────────────

def test_dashboard_no_cookie_redirects_to_login(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "login" in resp.headers["location"]


def test_dashboard_invalid_token_redirects_to_login(client: TestClient):
    resp = client.get("/", cookies={"rr_session": "garbage"})
    assert resp.status_code == 302
    assert "login" in resp.headers["location"]


def test_dashboard_valid_session_returns_200(client: TestClient):
    token = _make_session_token(1)
    resp = client.get("/", cookies={"rr_session": token})
    assert resp.status_code == 200
    assert b"Rival Radar" in resp.content


def test_dashboard_cache_control_no_store(client: TestClient):
    token = _make_session_token(1)
    resp = client.get("/", cookies={"rr_session": token})
    assert resp.headers.get("cache-control") == "no-store"


# ── GET /logout ────────────────────────────────────────────────────────────────

def test_logout_redirects_to_login(client: TestClient):
    resp = client.get("/logout")
    assert resp.status_code == 302
    assert "login" in resp.headers["location"]


def test_logout_clears_session_cookie(client: TestClient):
    token = _make_session_token(1)
    resp = client.get("/logout", cookies={"rr_session": token})
    set_cookie = resp.headers.get("set-cookie", "")
    assert "rr_session" in set_cookie
    assert "max-age=0" in set_cookie.lower()


# ── API auth ───────────────────────────────────────────────────────────────────

def test_api_no_auth_returns_401(client: TestClient):
    resp = client.get("/competitors")
    assert resp.status_code == 401


def test_api_valid_session_cookie_allowed(client: TestClient):
    token = _make_session_token(1)
    resp = client.get("/competitors", cookies={"rr_session": token})
    assert resp.status_code == 200


def test_api_valid_api_key_allowed(client: TestClient):
    resp = client.get("/competitors", headers={"X-API-Key": "changeme"})
    assert resp.status_code == 200


def test_api_wrong_api_key_rejected(client: TestClient):
    resp = client.get("/competitors", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


# ── GET /auth/google ───────────────────────────────────────────────────────────

def test_google_login_not_configured_redirects_to_login(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("rival_radar.api.settings.google_client_id", "")
    resp = client.get("/auth/google")
    assert resp.status_code == 302
    assert "login" in resp.headers["location"]


def test_google_callback_missing_state_rejected(client: TestClient):
    resp = client.get("/auth/google/callback?code=abc&state=xyz")
    assert resp.status_code == 302
    assert "error=2" in resp.headers["location"]


def test_google_callback_mismatched_state_rejected(client: TestClient):
    resp = client.get(
        "/auth/google/callback?code=abc&state=xyz",
        cookies={"oauth_state": "different_state"},
    )
    assert resp.status_code == 302
    assert "error=2" in resp.headers["location"]
