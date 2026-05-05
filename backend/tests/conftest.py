import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from alembic.config import Config
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import OperationalError

from alembic import command
from app.core.config import get_settings
from app.db.session import clear_database_caches
from app.main import create_app


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    get_settings.cache_clear()
    clear_database_caches()
    settings = get_settings()
    url = os.getenv("TEST_DATABASE_URL") or settings.test_database_url
    if not url:
        pytest.fail("DB-backed tests require TEST_DATABASE_URL to point at a test database.")

    app_url = os.getenv("DATABASE_URL") or settings.database_url
    assert_test_database_url(url, app_url)

    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    clear_database_caches()
    return url


@pytest.fixture
def migrated_database(database_url: str) -> Generator[Engine]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"Postgres is not reachable for DB-backed tests: {exc}")

    command.upgrade(Config("alembic.ini"), "head")

    truncate_database(engine)

    yield engine

    truncate_database(engine)
    engine.dispose()


@pytest.fixture
def test_key_pair() -> dict[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return {"private": private_pem, "public": public_pem}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, test_key_pair: dict[str, str]) -> Generator[TestClient]:
    monkeypatch.setenv("CLERK_JWT_PUBLIC_KEY", test_key_pair["public"])
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()
    clear_database_caches()
    app = create_app()

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    clear_database_caches()


@pytest.fixture
def make_clerk_token(test_key_pair: dict[str, str]):
    def _make_clerk_token(**claims: object) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": "user_2abc123",
            "sid": "sess_2abc123",
            "email": "alex@example.com",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            **claims,
        }
        return jwt.encode(payload, test_key_pair["private"], algorithm="RS256")

    return _make_clerk_token


def assert_test_database_url(test_database_url: str, app_database_url: str) -> None:
    test_url = make_url(test_database_url)
    app_url = make_url(app_database_url)
    if not _same_database(test_url, app_url):
        return

    pytest.fail(
        "DB-backed tests are destructive and require TEST_DATABASE_URL to point at a "
        "database separate from DATABASE_URL."
    )


def truncate_database(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
                    message_sources,
                    chat_messages,
                    chat_sessions,
                    document_embeddings,
                    ingestion_jobs,
                    document_chunks,
                    documents,
                    app_users
                """
            )
        )


def _same_database(first: URL, second: URL) -> bool:
    return (
        first.drivername == second.drivername
        and first.host == second.host
        and first.port == second.port
        and first.username == second.username
        and first.database == second.database
    )
