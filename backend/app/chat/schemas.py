from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MessageSourceResponse(BaseModel):
    id: UUID
    document_id: UUID
    document_name: str
    chunk_id: UUID
    rank: int
    score: float
    excerpt: str
    page_number: int | None = None
    section_title: str | None = None
    document_deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    status: str
    created_at: datetime
    model: str | None = None
    retrieval_query: str | None = None
    usage: dict[str, object] | None = None
    sources: list[MessageSourceResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ChatStreamMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class ChatStreamFinalEvent(BaseModel):
    assistant_message_id: UUID
    session_id: UUID
    sources: list[MessageSourceResponse]
    model: str
    usage: dict[str, object] | None = None


class ChatStreamErrorEvent(BaseModel):
    message: str
    retryable: bool


class ChatSessionSummary(BaseModel):
    id: UUID
    title: str
    title_status: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    last_message: ChatMessageResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class ChatSessionDetail(BaseModel):
    id: UUID
    title: str
    title_status: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    messages: list[ChatMessageResponse]

    model_config = ConfigDict(from_attributes=True)
