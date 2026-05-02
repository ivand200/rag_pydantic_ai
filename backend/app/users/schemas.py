from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AppUserIdentity(BaseModel):
    id: UUID
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
