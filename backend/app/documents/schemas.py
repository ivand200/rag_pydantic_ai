from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentUser(BaseModel):
    id: UUID
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    media_type: str
    byte_size: int
    status: str
    uploaded_by: DocumentUser
    uploaded_at: datetime
    deleted: bool
    deleted_at: datetime | None = None
    failure_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)
