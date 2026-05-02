from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_current_app_user
from app.models.app_user import AppUser
from app.users.schemas import AppUserIdentity

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=AppUserIdentity)
def read_me(app_user: Annotated[AppUser, Depends(get_current_app_user)]) -> AppUserIdentity:
    return AppUserIdentity.model_validate(app_user)
