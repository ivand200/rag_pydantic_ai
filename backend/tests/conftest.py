from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


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
    app = create_app()

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


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
