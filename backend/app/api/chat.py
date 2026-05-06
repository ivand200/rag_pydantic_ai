import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import StreamingResponse

from app.auth.clerk import CurrentUser
from app.chat.rag_orchestration import (
    RAGOrchestrationResult,
    RAGOrchestrationService,
    RAGOrchestrationStreamDelta,
    RAGOrchestrationStreamFinal,
    build_openai_chat_model,
    build_rag_orchestration_service,
)
from app.chat.schemas import (
    ChatMessageResponse,
    ChatSessionDetail,
    ChatSessionSummary,
    ChatStreamErrorEvent,
    ChatStreamFinalEvent,
    ChatStreamMessageRequest,
)
from app.chat.service import (
    EmptyChatMessageError,
    append_assistant_message_with_sources_for_app_user_id,
    append_chat_message,
    create_chat_session,
    delete_chat_session,
    list_chat_sessions,
    load_chat_session,
)
from app.chat.title_generation import ChatTitleGenerator, PydanticAIChatTitleGenerator
from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.dependencies import get_current_app_user, get_current_user, get_db_session
from app.models.app_user import AppUser
from app.retrieval.embeddings import OpenAIEmbeddingProvider
from app.users.sync import get_or_sync_app_user

router = APIRouter(prefix="/api/chat/sessions", tags=["chat"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[ChatSessionSummary])
def list_sessions(
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[ChatSessionSummary]:
    return list_chat_sessions(db=db, app_user=app_user)


@router.post("", response_model=ChatSessionDetail, status_code=201)
def create_session(
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ChatSessionDetail:
    return create_chat_session(db=db, app_user=app_user)


@router.get("/{session_id}", response_model=ChatSessionDetail)
def load_session(
    session_id: UUID,
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ChatSessionDetail:
    session = load_chat_session(db=db, app_user=app_user, session_id=session_id)
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "chat_session_not_found"})
    return session


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: UUID,
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    deleted = delete_chat_session(db=db, app_user=app_user, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"code": "chat_session_not_found"})
    return Response(status_code=204)


def get_rag_orchestration_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RAGOrchestrationService:
    return build_rag_orchestration_service(
        settings=settings,
        embedding_provider=OpenAIEmbeddingProvider(settings=settings),
    )


def get_chat_title_generator(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatTitleGenerator:
    return PydanticAIChatTitleGenerator(model=build_openai_chat_model(settings=settings))


def get_chat_sessionmaker() -> sessionmaker[Session]:
    return get_sessionmaker()


@router.post("/{session_id}/messages/stream")
def stream_message(
    session_id: UUID,
    request: ChatStreamMessageRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rag_service: Annotated[RAGOrchestrationService, Depends(get_rag_orchestration_service)],
    title_generator: Annotated[ChatTitleGenerator, Depends(get_chat_title_generator)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_chat_sessionmaker)],
) -> StreamingResponse:
    with session_factory() as db:
        app_user = get_or_sync_app_user(db, current_user)
        try:
            user_message = append_chat_message(
                db=db,
                app_user=app_user,
                session_id=session_id,
                role="user",
                content=request.content,
                chat_model=settings.chat_model,
                title_generator=title_generator,
            )
        except EmptyChatMessageError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "empty_chat_message", "message": str(exc)},
            ) from exc

        if user_message is None:
            raise HTTPException(status_code=404, detail={"code": "chat_session_not_found"})

        app_user_id = app_user.id
        user_message_id = user_message.id
        db.commit()

    stream_run_id = str(uuid4())
    return StreamingResponse(
        _stream_chat_events(
            session_factory=session_factory,
            app_user_id=app_user_id,
            session_id=session_id,
            user_message_id=user_message_id,
            current_message=request.content,
            rag_service=rag_service,
            stream_run_id=stream_run_id,
        ),
        media_type="text/event-stream",
    )


async def _stream_chat_events(
    *,
    session_factory: sessionmaker[Session],
    app_user_id: UUID,
    session_id: UUID,
    user_message_id: UUID,
    current_message: str,
    rag_service: RAGOrchestrationService,
    stream_run_id: str,
) -> AsyncIterator[str]:
    try:
        logger.info(
            "Chat stream started.",
            extra={
                "event": "chat.stream_started",
                "stream_run_id": stream_run_id,
                "session_id": str(session_id),
                "message_id": str(user_message_id),
            },
        )
        result = None
        prepared_context = await rag_service.prepare_stream_context(
            session_factory=session_factory,
            session_id=session_id,
            current_message=current_message,
            current_message_id=user_message_id,
            stream_run_id=stream_run_id,
        )

        if not prepared_context.answer_sources:
            logger.info(
                "Chat stream has no sources.",
                extra={
                    "event": "chat.no_source",
                    "stream_run_id": stream_run_id,
                    "session_id": str(session_id),
                    "message_id": str(user_message_id),
                    "source_count": 0,
                },
            )
        async for event in rag_service.stream_prepared_answer(prepared_context):
            if isinstance(event, RAGOrchestrationStreamDelta):
                yield _sse_event("delta", {"text": event.text})
            elif isinstance(event, RAGOrchestrationStreamFinal):
                result = event.result

        if result is None:
            raise RuntimeError("Chat generation completed without a final event.")

        logger.info(
            "Chat answer completed.",
            extra={
                "event": "chat.answer.completed",
                "stream_run_id": stream_run_id,
                "session_id": str(session_id),
                "message_id": str(user_message_id),
                "source_count": len(result.sources),
            },
        )
        assistant_message = _persist_assistant_message(
            session_factory=session_factory,
            app_user_id=app_user_id,
            session_id=session_id,
            result=result,
        )
        final = ChatStreamFinalEvent(
            assistant_message_id=assistant_message.id,
            session_id=session_id,
            sources=assistant_message.sources,
            model=result.model,
            usage=result.usage,
        )
        logger.info(
            "Chat persistence completed.",
            extra={
                "event": "chat.persistence.completed",
                "stream_run_id": stream_run_id,
                "session_id": str(session_id),
                "message_id": str(assistant_message.id),
                "source_count": len(assistant_message.sources),
            },
        )
        yield _sse_event("final", final.model_dump(mode="json"))
    except Exception:
        logger.exception(
            "Chat stream generation failed for session %s",
            session_id,
            extra={
                "event": "chat.stream_error",
                "stream_run_id": stream_run_id,
                "session_id": str(session_id),
                "message_id": str(user_message_id),
            },
        )
        error = ChatStreamErrorEvent(message="Chat generation failed.", retryable=True)
        yield _sse_event("error", error.model_dump(mode="json"))


def _persist_assistant_message(
    *,
    session_factory: sessionmaker[Session],
    app_user_id: UUID,
    session_id: UUID,
    result: RAGOrchestrationResult,
) -> ChatMessageResponse:
    with session_factory() as db:
        try:
            assistant_message = append_assistant_message_with_sources_for_app_user_id(
                db=db,
                app_user_id=app_user_id,
                session_id=session_id,
                content=result.answer,
                model=result.model,
                retrieval_query=result.retrieval_query,
                usage=result.usage,
                sources=result.sources,
            )
            if assistant_message is None:
                raise RuntimeError("Chat session is no longer available.")

            db.commit()
            return assistant_message
        except Exception:
            db.rollback()
            raise


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
