"""Tests for three coverage gaps:
1. SSRF rejection at the API layer (POST /competitors)
2. /health endpoint shape
3. Google OAuth happy path (POST /auth/google/callback)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rival_radar.api import _make_session_token, app, limiter
from rival_radar.database import get_session
from rival_radar.models import Base

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


# ── GROUP 1: SSRF rejection at API layer ──────────────────────────────────────

@pytest.mark.parametrize("malicious_url", [
    "http://127.0.0.1/",
    "http://192.168.1.1/",
    "ftp://evil.com",
    "http://10.0.0.1/",
])
def test_post_competitors_rejects_ssrf_url(client: TestClient, malicious_url: str):
    """POST /competitors with private/non-http URLs must return 422."""
    token = _make_session_token(1)
    resp = client.post(
        "/competitors",
        json={"name": "Evil Corp", "urls": [malicious_url]},
        cookies={"rr_session": token},
    )
    assert resp.status_code == 422, (
        f"Expected 422 for SSRF URL {malicious_url!r}, got {resp.status_code}: {resp.text}"
    )


# ── GROUP 2: /health endpoint shape ───────────────────────────────────────────

def test_health_returns_200(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_body_has_status_ok(client: TestClient):
    resp = client.get("/health")
    assert resp.json()["status"] == "ok"


def test_health_body_has_service_rival_radar(client: TestClient):
    resp = client.get("/health")
    assert resp.json()["service"] == "rival-radar"


def test_health_full_shape(client: TestClient):
    """Verify the complete response body in a single assertion."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "rival-radar"}


# ── GROUP 3: Google OAuth happy path ──────────────────────────────────────────

def _make_mock_httpx_client(access_token: str = "tok_abc123", google_id: str = "g-uid-999",
                             email: str = "oauthuser@example.com", name: str = "OAuth User"):
    """Return a mock async context manager that simulates a successful Google OAuth exchange."""
    # Token response mock
    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {"access_token": access_token}

    # Userinfo response mock
    userinfo_response = MagicMock()
    userinfo_response.status_code = 200
    userinfo_response.json.return_value = {
        "id": google_id,
        "email": email,
        "name": name,
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.post = AsyncMock(return_value=token_response)
    mock_client_instance.get = AsyncMock(return_value=userinfo_response)

    # Make the async context manager work: `async with httpx.AsyncClient() as client:`
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_async_client_cls = MagicMock(return_value=mock_context)
    return mock_async_client_cls


def test_google_callback_happy_path_redirects_to_root(client: TestClient):
    """Successful Google OAuth callback should redirect to '/'."""
    state = "test-state-value-abc123"
    mock_async_client_cls = _make_mock_httpx_client()

    with patch("rival_radar.api.settings.google_client_id", "fake-client-id"), \
         patch("rival_radar.api.settings.google_client_secret", "fake-secret"), \
         patch("rival_radar.api.httpx.AsyncClient", mock_async_client_cls):
        resp = client.get(
            f"/auth/google/callback?code=authcode123&state={state}",
            cookies={"oauth_state": state},
        )

    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


def test_google_callback_happy_path_sets_session_cookie(client: TestClient):
    """Successful Google OAuth callback should set the rr_session cookie."""
    state = "test-state-value-xyz789"
    mock_async_client_cls = _make_mock_httpx_client(
        google_id="g-uid-777", email="newgoogleuser@example.com"
    )

    with patch("rival_radar.api.settings.google_client_id", "fake-client-id"), \
         patch("rival_radar.api.settings.google_client_secret", "fake-secret"), \
         patch("rival_radar.api.httpx.AsyncClient", mock_async_client_cls):
        resp = client.get(
            f"/auth/google/callback?code=authcode456&state={state}",
            cookies={"oauth_state": state},
        )

    assert "rr_session" in resp.cookies, (
        f"Expected rr_session cookie in response, got cookies: {dict(resp.cookies)}"
    )


def test_google_callback_happy_path_clears_oauth_state_cookie(client: TestClient):
    """Successful Google OAuth callback should clear the oauth_state cookie."""
    state = "test-state-value-clear123"
    mock_async_client_cls = _make_mock_httpx_client(
        google_id="g-uid-888", email="cleartest@example.com"
    )

    with patch("rival_radar.api.settings.google_client_id", "fake-client-id"), \
         patch("rival_radar.api.settings.google_client_secret", "fake-secret"), \
         patch("rival_radar.api.httpx.AsyncClient", mock_async_client_cls):
        resp = client.get(
            f"/auth/google/callback?code=authcode789&state={state}",
            cookies={"oauth_state": state},
        )

    # The session cookie is set; oauth_state should be cleared
    assert resp.status_code == 302
    # oauth_state cookie cleared means either not present in new cookies or max-age=0
    # TestClient reflects the final cookie jar; oauth_state should not appear in new cookies
    assert "oauth_state" not in resp.cookies


def test_google_callback_creates_new_user_in_db(client: TestClient):
    """Successful Google OAuth callback should create the user if they don't exist."""
    from rival_radar.models import User

    state = "test-state-new-user-111"
    google_id = "brand-new-google-uid-555"
    email = "brandnew@example.com"
    mock_async_client_cls = _make_mock_httpx_client(google_id=google_id, email=email)

    with patch("rival_radar.api.settings.google_client_id", "fake-client-id"), \
         patch("rival_radar.api.settings.google_client_secret", "fake-secret"), \
         patch("rival_radar.api.httpx.AsyncClient", mock_async_client_cls):
        resp = client.get(
            f"/auth/google/callback?code=authcodeNewUser&state={state}",
            cookies={"oauth_state": state},
        )

    assert resp.status_code == 302

    # Verify user was persisted to the in-memory DB
    s = _Session()
    user = s.query(User).filter(User.google_id == google_id).first()
    s.close()
    assert user is not None, f"Expected user with google_id={google_id!r} to be in the DB"
    assert user.email == email
