from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.chat.rag_orchestration import SourceCitationPayload
from app.chat.schemas import (
    ChatMessageResponse,
    ChatSessionDetail,
    ChatSessionSummary,
    MessageSourceResponse,
)
from app.chat.title_generation import ChatTitleGenerator, fallback_title
from app.models.app_user import AppUser
from app.models.rag import ChatMessage, ChatSession, MessageSource

CHAT_SESSION_PENDING_TITLE = "New chat"
TITLE_STATUS_PENDING = "pending"
TITLE_STATUS_GENERATED = "generated"
TITLE_STATUS_FALLBACK = "fallback"
MESSAGE_STATUS_COMPLETED = "completed"

ChatRole = Literal["user", "assistant"]


class EmptyChatMessageError(ValueError):
    pass


def create_chat_session(*, db: Session, app_user: AppUser) -> ChatSessionDetail:
    now = datetime.now(UTC)
    session = ChatSession(
        id=uuid4(),
        app_user_id=app_user.id,
        title=CHAT_SESSION_PENDING_TITLE,
        title_status=TITLE_STATUS_PENDING,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.flush()
    return _session_detail(session=session, messages=[])


def list_chat_sessions(*, db: Session, app_user: AppUser) -> list[ChatSessionSummary]:
    sessions = db.execute(
        select(ChatSession)
        .where(ChatSession.app_user_id == app_user.id)
        .order_by(
            func.coalesce(ChatSession.last_message_at, ChatSession.created_at).desc(),
            ChatSession.created_at.desc(),
        )
    ).scalars()

    return [
        _session_summary(session=session, last_message=_load_last_message(db, session.id))
        for session in sessions
    ]


def load_chat_session(
    *,
    db: Session,
    app_user: AppUser,
    session_id: UUID,
) -> ChatSessionDetail | None:
    session = _owned_session(db=db, app_user=app_user, session_id=session_id)
    if session is None:
        return None

    messages = db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    ).scalars()
    return _session_detail(
        session=session,
        messages=[
            _message_response(message, _load_sources(db, message.id)) for message in messages
        ],
    )


def delete_chat_session(*, db: Session, app_user: AppUser, session_id: UUID) -> bool:
    session = _owned_session(db=db, app_user=app_user, session_id=session_id)
    if session is None:
        return False

    message_ids = select(ChatMessage.id).where(ChatMessage.session_id == session.id)
    db.execute(delete(MessageSource).where(MessageSource.message_id.in_(message_ids)))
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
    db.execute(delete(ChatSession).where(ChatSession.id == session.id))
    db.flush()
    return True


def append_chat_message(
    *,
    db: Session,
    app_user: AppUser,
    session_id: UUID,
    role: ChatRole,
    content: str,
    chat_model: str,
    title_generator: ChatTitleGenerator | None = None,
    model: str | None = None,
    retrieval_query: str | None = None,
    usage: dict[str, object] | None = None,
) -> ChatMessageResponse | None:
    session = _owned_session(db=db, app_user=app_user, session_id=session_id)
    if session is None:
        return None

    if not content.strip():
        raise EmptyChatMessageError("Chat messages must include non-empty content.")

    should_generate_title = role == "user" and _should_generate_title(db=db, session=session)
    now = datetime.now(UTC)
    message = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        role=role,
        content=content,
        status=MESSAGE_STATUS_COMPLETED,
        model=model,
        retrieval_query=retrieval_query,
        usage=usage,
        created_at=now,
    )
    db.add(message)
    session.last_message_at = now
    session.updated_at = now

    if should_generate_title:
        session.title, session.title_status = _title_for_first_message(
            first_message=content,
            chat_model=chat_model,
            title_generator=title_generator,
        )

    db.flush()
    return _message_response(message, [])


def append_assistant_message_with_sources(
    *,
    db: Session,
    app_user: AppUser,
    session_id: UUID,
    content: str,
    model: str,
    retrieval_query: str,
    usage: dict[str, object] | None,
    sources: list[SourceCitationPayload],
) -> ChatMessageResponse | None:
    session = _owned_session(db=db, app_user=app_user, session_id=session_id)
    if session is None:
        return None

    return _append_assistant_message_with_sources_for_session(
        db=db,
        session=session,
        content=content,
        model=model,
        retrieval_query=retrieval_query,
        usage=usage,
        sources=sources,
    )


def append_assistant_message_with_sources_for_app_user_id(
    *,
    db: Session,
    app_user_id: UUID,
    session_id: UUID,
    content: str,
    model: str,
    retrieval_query: str,
    usage: dict[str, object] | None,
    sources: list[SourceCitationPayload],
) -> ChatMessageResponse | None:
    session = _owned_session_by_app_user_id(
        db=db,
        app_user_id=app_user_id,
        session_id=session_id,
    )
    if session is None:
        return None

    return _append_assistant_message_with_sources_for_session(
        db=db,
        session=session,
        content=content,
        model=model,
        retrieval_query=retrieval_query,
        usage=usage,
        sources=sources,
    )


def _owned_session(*, db: Session, app_user: AppUser, session_id: UUID) -> ChatSession | None:
    return db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.app_user_id == app_user.id,
        )
    ).scalar_one_or_none()


def _owned_session_by_app_user_id(
    *,
    db: Session,
    app_user_id: UUID,
    session_id: UUID,
) -> ChatSession | None:
    return db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.app_user_id == app_user_id,
        )
    ).scalar_one_or_none()


def _append_assistant_message_with_sources_for_session(
    *,
    db: Session,
    session: ChatSession,
    content: str,
    model: str,
    retrieval_query: str,
    usage: dict[str, object] | None,
    sources: list[SourceCitationPayload],
) -> ChatMessageResponse:
    if not content.strip():
        raise EmptyChatMessageError("Chat messages must include non-empty content.")

    now = datetime.now(UTC)
    message = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        role="assistant",
        content=content,
        status=MESSAGE_STATUS_COMPLETED,
        model=model,
        retrieval_query=retrieval_query,
        usage=usage,
        created_at=now,
    )
    db.add(message)
    session.last_message_at = now
    session.updated_at = now
    db.flush()

    source_rows = [
        MessageSource(
            id=uuid4(),
            message_id=message.id,
            document_id=source.document_id,
            document_name=source.document_name,
            chunk_id=source.chunk_id,
            rank=source.rank,
            score=source.score,
            excerpt=source.excerpt,
            page_number=source.page_number,
            section_title=source.section_title,
        )
        for source in sources
    ]
    db.add_all(source_rows)
    db.flush()
    return _message_response(
        message,
        [MessageSourceResponse.model_validate(source) for source in source_rows],
    )


def _should_generate_title(*, db: Session, session: ChatSession) -> bool:
    if session.title_status != TITLE_STATUS_PENDING:
        return False

    accepted_user_messages = db.execute(
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.session_id == session.id, ChatMessage.role == "user")
    ).scalar_one()
    return accepted_user_messages == 0


def _title_for_first_message(
    *,
    first_message: str,
    chat_model: str,
    title_generator: ChatTitleGenerator | None,
) -> tuple[str, str]:
    if title_generator is not None:
        try:
            raw_title = title_generator.generate_title(
                first_message=first_message,
                model=chat_model,
            )
            generated = " ".join(raw_title.split())
        except Exception:
            generated = ""

        if generated:
            return generated, TITLE_STATUS_GENERATED

    return fallback_title(first_message), TITLE_STATUS_FALLBACK


def _load_last_message(db: Session, session_id: UUID) -> ChatMessageResponse | None:
    message = db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if message is None:
        return None
    return _message_response(message, _load_sources(db, message.id))


def _load_sources(db: Session, message_id: UUID) -> list[MessageSourceResponse]:
    sources = db.execute(
        select(MessageSource)
        .where(MessageSource.message_id == message_id)
        .order_by(MessageSource.rank.asc())
    ).scalars()
    return [MessageSourceResponse.model_validate(source) for source in sources]


def _session_summary(
    *,
    session: ChatSession,
    last_message: ChatMessageResponse | None,
) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        title_status=session.title_status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_message_at=session.last_message_at,
        last_message=last_message,
    )


def _session_detail(
    *,
    session: ChatSession,
    messages: Iterable[ChatMessageResponse],
) -> ChatSessionDetail:
    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        title_status=session.title_status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_message_at=session.last_message_at,
        messages=list(messages),
    )


def _message_response(
    message: ChatMessage,
    sources: list[MessageSourceResponse],
) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        status=message.status,
        created_at=message.created_at,
        model=message.model,
        retrieval_query=message.retrieval_query,
        usage=message.usage,
        sources=sources,
    )
