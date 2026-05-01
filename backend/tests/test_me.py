from collections.abc import Callable

from fastapi.testclient import TestClient


def test_me_rejects_missing_bearer_token(client: TestClient) -> None:
    response = client.get("/api/me")

    assert response.status_code == 401


def test_me_rejects_invalid_bearer_token(client: TestClient) -> None:
    response = client.get("/api/me", headers={"Authorization": "Bearer not-a-real-jwt"})

    assert response.status_code == 401


def test_me_returns_normalized_clerk_user(
    client: TestClient,
    make_clerk_token: Callable[..., str],
) -> None:
    token = make_clerk_token(first_name="Alex", last_name="Rivera")

    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "user_2abc123",
        "session_id": "sess_2abc123",
        "email": "alex@example.com",
        "first_name": "Alex",
        "last_name": "Rivera",
    }
