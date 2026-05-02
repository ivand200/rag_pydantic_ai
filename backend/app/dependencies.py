from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.clerk import CurrentUser, verify_clerk_jwt
from app.core.config import Settings, get_settings
from app.db.session import session_scope
from app.models.app_user import AppUser
from app.users.sync import get_or_sync_app_user

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    return verify_clerk_jwt(credentials.credentials, settings)


def get_db_session() -> Generator[Session]:
    yield from session_scope()


def get_current_app_user(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> AppUser:
    return get_or_sync_app_user(db, current_user)
