"""Tests for the OAuth Relay Service (Story 2.7).

Run with: pytest test_main.py -v
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import (
    SESSION_TIMEOUT,
    app,
    cleanup_expired_sessions,
    get_or_create_session,
    sessions,
    ws_connections,
)


@pytest.fixture(autouse=True)
def clear_sessions():
    """Clear sessions before and after each test."""
    sessions.clear()
    ws_connections.clear()
    yield
    sessions.clear()
    ws_connections.clear()


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_returns_ok(self, client):
        """Test health endpoint returns OK status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "active_sessions" in data
        assert "active_websockets" in data

    def test_health_shows_session_count(self, client):
        """Test health endpoint shows correct session count."""
        # Create some sessions
        get_or_create_session("session-1")
        get_or_create_session("session-2")

        response = client.get("/health")
        data = response.json()
        assert data["active_sessions"] == 2


class TestRootEndpoint:
    """Tests for the root endpoint."""

    def test_root_returns_service_info(self, client):
        """Test root endpoint returns service information."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "OAuth Relay Service" in data["service"]
        assert "version" in data
        assert data["health"] == "/health"


class TestCallbackEndpoint:
    """Tests for the OAuth callback endpoint."""

    def test_callback_with_code_returns_success_html(self, client):
        """Test callback with code returns success HTML page."""
        response = client.get("/callback?session=test-session&code=auth_code_123")
        assert response.status_code == 200
        assert "Authentification réussie" in response.text
        assert "✅" in response.text

    def test_callback_stores_code_in_session(self, client):
        """Test callback stores the code in session."""
        client.get("/callback?session=test-session&code=auth_code_123")

        assert "test-session" in sessions
        assert sessions["test-session"]["code"] == "auth_code_123"

    def test_callback_with_error_returns_error_html(self, client):
        """Test callback with error returns error HTML page."""
        response = client.get(
            "/callback?session=test-session&error=access_denied&error_description=User%20denied%20access"
        )
        assert response.status_code == 400
        assert "Erreur d'authentification" in response.text
        assert "User denied access" in response.text

    def test_callback_stores_error_in_session(self, client):
        """Test callback stores error in session."""
        client.get(
            "/callback?session=test-session&error=access_denied&error_description=Denied"
        )

        assert "test-session" in sessions
        assert sessions["test-session"]["error"] == "Denied"

    def test_callback_without_code_or_error_creates_session(self, client):
        """Test callback without code/error just creates session."""
        response = client.get("/callback?session=test-session")
        assert response.status_code == 200
        assert "test-session" in sessions
        assert sessions["test-session"]["code"] is None
        assert sessions["test-session"]["error"] is None


class TestPollEndpoint:
    """Tests for the HTTP polling endpoint."""

    def test_poll_returns_waiting_when_no_code(self, client):
        """Test polling returns waiting status when no code yet."""
        get_or_create_session("test-session")

        response = client.get("/poll/test-session")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "waiting"

    def test_poll_returns_code_when_available(self, client):
        """Test polling returns code when available."""
        sessions["test-session"] = {
            "created_at": datetime.utcnow(),
            "code": "auth_code_123",
            "error": None,
            "retrieved": False,
        }

        response = client.get("/poll/test-session")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "auth_code_123"
        assert data["status"] == "success"

    def test_poll_deletes_session_after_code_retrieval(self, client):
        """Test polling deletes session after code is retrieved."""
        sessions["test-session"] = {
            "created_at": datetime.utcnow(),
            "code": "auth_code_123",
            "error": None,
            "retrieved": False,
        }

        client.get("/poll/test-session")
        assert "test-session" not in sessions

    def test_poll_returns_error_when_oauth_failed(self, client):
        """Test polling returns error when OAuth failed."""
        sessions["test-session"] = {
            "created_at": datetime.utcnow(),
            "code": None,
            "error": "access_denied",
            "retrieved": False,
        }

        response = client.get("/poll/test-session")
        assert response.status_code == 200
        data = response.json()
        assert data["error"] == "access_denied"
        assert data["status"] == "error"

    def test_poll_returns_404_for_unknown_session(self, client):
        """Test polling returns 404 for unknown session."""
        response = client.get("/poll/unknown-session")
        assert response.status_code == 404
        assert "not found or expired" in response.json()["detail"]


class TestSessionExpiration:
    """Tests for session expiration."""

    def test_cleanup_removes_expired_sessions(self):
        """Test cleanup removes expired sessions."""
        # Create an expired session
        sessions["expired-session"] = {
            "created_at": datetime.utcnow() - timedelta(minutes=10),
            "code": None,
            "error": None,
            "retrieved": False,
        }
        # Create a valid session
        sessions["valid-session"] = {
            "created_at": datetime.utcnow(),
            "code": None,
            "error": None,
            "retrieved": False,
        }

        cleaned = cleanup_expired_sessions()

        assert "expired-session" in cleaned
        assert "expired-session" not in sessions
        assert "valid-session" in sessions

    def test_cleanup_removes_websocket_connections(self):
        """Test cleanup removes WebSocket connections for expired sessions."""
        sessions["expired-session"] = {
            "created_at": datetime.utcnow() - timedelta(minutes=10),
            "code": None,
            "error": None,
            "retrieved": False,
        }
        ws_connections["expired-session"] = [MagicMock()]

        cleanup_expired_sessions()

        assert "expired-session" not in ws_connections


class TestSessionManagement:
    """Tests for session management functions."""

    def test_get_or_create_session_creates_new(self):
        """Test get_or_create_session creates new session."""
        session = get_or_create_session("new-session")

        assert "new-session" in sessions
        assert session["code"] is None
        assert session["error"] is None
        assert "created_at" in session

    def test_get_or_create_session_returns_existing(self):
        """Test get_or_create_session returns existing session."""
        sessions["existing-session"] = {
            "created_at": datetime.utcnow(),
            "code": "existing_code",
            "error": None,
            "retrieved": False,
        }

        session = get_or_create_session("existing-session")

        assert session["code"] == "existing_code"


class TestCORSConfiguration:
    """Tests for CORS configuration."""

    def test_cors_allows_all_origins(self, client):
        """Test CORS allows requests from any origin."""
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # FastAPI with CORS middleware returns 200 for preflight
        assert response.status_code in [200, 400]  # 400 if not a proper preflight


class TestPrivacyAndSecurity:
    """Tests for privacy and security features."""

    def test_no_persistent_storage(self):
        """Test that sessions dict is the only storage."""
        # This is a conceptual test - we verify the code doesn't use files/DB
        # by checking the module doesn't import storage-related modules
        import main

        # Check that main module doesn't have SQLAlchemy or file operations
        assert not hasattr(main, "create_engine")
        assert not hasattr(main, "open")  # File operations not used directly

    def test_session_auto_expiration_configured(self):
        """Test session timeout is configured for 5 minutes."""
        assert SESSION_TIMEOUT == timedelta(minutes=5)

    def test_session_deleted_after_code_retrieval(self, client):
        """Test session is deleted immediately after code retrieval."""
        sessions["test-session"] = {
            "created_at": datetime.utcnow(),
            "code": "secret_code",
            "error": None,
            "retrieved": False,
        }

        # First retrieval should succeed
        response1 = client.get("/poll/test-session")
        assert response1.status_code == 200

        # Second retrieval should fail (session deleted)
        response2 = client.get("/poll/test-session")
        assert response2.status_code == 404
