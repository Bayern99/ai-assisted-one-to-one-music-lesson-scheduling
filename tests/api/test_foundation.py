from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from modules.api.app import create_app
from modules.api.config import AppConfig


def test_health_is_public(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_private_route_rejects_missing_cookie(client):
    response = client.get("/api/auth/session")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_bootstrap_exchange_sets_strict_cookie(client, bootstrap_token):
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"authenticated": True}
    assert "pi_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


def test_bootstrap_exchange_rejects_bad_token_with_envelope(client):
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": "wrong-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_session_accepts_exchanged_cookie(client, bootstrap_token):
    exchange_response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )

    assert exchange_response.status_code == 200
    response = client.get("/api/auth/session")
    assert response.status_code == 200
    assert response.json()["data"] == {"authenticated": True}


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


def test_untrusted_host_uses_error_envelope(client):
    response = client.get("/api/health", headers={"Host": "example.com"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HOST"


def test_production_cors_is_closed(client):
    response = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_configured_dev_origin_is_the_only_allowed_cors_origin(tmp_path: Path):
    app = create_app(
        AppConfig(
            base_dir=tmp_path,
            bootstrap_token="test-token",
            frontend_dir=None,
            allow_test_host=True,
            dev_origin="http://localhost:5173",
        )
    )

    with TestClient(app) as client:
        allowed = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        blocked = client.options(
            "/api/health",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers
    assert blocked.json()["error"]["code"] == "CORS_REJECTED"


def test_untrusted_host_rejects_allowed_origin_preflight(tmp_path: Path):
    app = create_app(
        AppConfig(
            base_dir=tmp_path,
            bootstrap_token="test-token",
            frontend_dir=None,
            allow_test_host=True,
            dev_origin="http://localhost:5173",
        )
    )

    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Host": "example.com",
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HOST"
