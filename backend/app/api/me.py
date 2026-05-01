from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.clerk import CurrentUser
from app.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=CurrentUser)
def read_me(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    return current_user
