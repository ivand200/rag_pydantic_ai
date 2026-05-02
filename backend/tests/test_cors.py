from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.main import create_app

FRONTEND_ORIGIN = "http://localhost:5173"
ALTERNATE_FRONTEND_ORIGIN = "http://127.0.0.1:5173"
UNTRUSTED_ORIGIN = "http://localhost:3000"


def test_cors_preflight_allows_frontend_authorization_header(client: TestClient) -> None:
    response = client.options(
        "/api/me",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_protected_response_exposes_cors_headers_for_frontend_origin(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    token = make_clerk_token()

    response = client.get(
        "/api/me",
        headers={
            "Origin": FRONTEND_ORIGIN,
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_cors_preflight_rejects_unconfigured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/me",
        headers={
            "Origin": UNTRUSTED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_configured_additional_origin(monkeypatch) -> None:
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", f"{FRONTEND_ORIGIN},{ALTERNATE_FRONTEND_ORIGIN}")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.options(
            "/api/me",
            headers={
                "Origin": ALTERNATE_FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

    get_settings.cache_clear()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALTERNATE_FRONTEND_ORIGIN
