from typing import Any

import jwt
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings


class CurrentUser(BaseModel):
    user_id: str = Field(..., description="Clerk user id from the JWT subject claim.")
    session_id: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    model_config = ConfigDict(frozen=True)


def verify_clerk_jwt(token: str, settings: Settings) -> CurrentUser:
    public_key = _normalize_public_key(settings.clerk_jwt_public_key)
    if not public_key:
        raise _unauthorized()

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise _unauthorized()

    return CurrentUser(
        user_id=subject,
        session_id=_optional_string(claims.get("sid")),
        email=_email_from_claims(claims),
        first_name=_optional_string(claims.get("first_name")),
        last_name=_optional_string(claims.get("last_name")),
    )


def _normalize_public_key(value: str | None) -> str | None:
    if not value:
        return None

    return value.replace("\\n", "\n").strip()


def _email_from_claims(claims: dict[str, Any]) -> str | None:
    direct_email = _optional_string(claims.get("email"))
    if direct_email:
        return direct_email

    email_claims = claims.get("email_addresses")
    if isinstance(email_claims, list):
        for email_claim in email_claims:
            if not isinstance(email_claim, dict):
                continue
            email = _optional_string(email_claim.get("email_address"))
            if email:
                return email

    return None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
