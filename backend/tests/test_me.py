from collections.abc import Callable
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


def app_user_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM app_users")).scalar_one()


def test_me_rejects_missing_bearer_token_without_writing_user(
    client: TestClient,
    migrated_database: Engine,
) -> None:
    response = client.get("/api/me")

    assert response.status_code == 401
    assert app_user_count(migrated_database) == 0


def test_me_rejects_invalid_bearer_token_without_writing_user(
    client: TestClient,
    migrated_database: Engine,
) -> None:
    response = client.get("/api/me", headers={"Authorization": "Bearer not-a-real-jwt"})

    assert response.status_code == 401
    assert app_user_count(migrated_database) == 0


def test_me_creates_local_app_user_from_verified_clerk_identity(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    token = make_clerk_token(first_name="Alex", last_name="Rivera")

    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": body["id"],
        "email": "alex@example.com",
        "first_name": "Alex",
        "last_name": "Rivera",
    }
    UUID(body["id"])
    assert app_user_count(migrated_database) == 1


def test_me_reuses_local_app_user_and_updates_synced_profile_fields(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    first_token = make_clerk_token(email="alex@example.com", first_name="Alex", last_name="Rivera")
    first_response = client.get("/api/me", headers={"Authorization": f"Bearer {first_token}"})

    second_token = make_clerk_token(
        email="alex.updated@example.com",
        first_name="Avery",
        last_name="Stone",
    )
    second_response = client.get("/api/me", headers={"Authorization": f"Bearer {second_token}"})

    assert second_response.status_code == 200
    assert second_response.json() == {
        "id": first_response.json()["id"],
        "email": "alex.updated@example.com",
        "first_name": "Avery",
        "last_name": "Stone",
    }
    assert app_user_count(migrated_database) == 1
