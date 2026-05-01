from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.clerk import CurrentUser, verify_clerk_jwt
from app.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    return verify_clerk_jwt(credentials.credentials, settings)
