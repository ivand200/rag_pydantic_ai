import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.chat.rag_orchestration import (
    RAGOrchestrationService,
    RAGOrchestrationStreamDelta,
    RAGOrchestrationStreamFinal,
    build_openai_chat_model,
    build_rag_orchestration_service,
)
from app.chat.schemas import (
    ChatSessionDetail,
    ChatSessionSummary,
    ChatStreamErrorEvent,
    ChatStreamFinalEvent,
    ChatStreamMessageRequest,
)
from app.chat.service import (
    EmptyChatMessageError,
    append_assistant_message_with_sources,
    append_chat_message,
    create_chat_session,
    delete_chat_session,
    list_chat_sessions,
    load_chat_session,
)
from app.chat.title_generation import ChatTitleGenerator, PydanticAIChatTitleGenerator
from app.core.config import Settings, get_settings
from app.dependencies import get_current_app_user, get_db_session
from app.models.app_user import AppUser
from app.retrieval.embeddings import OpenAIEmbeddingProvider

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


@router.post("/{session_id}/messages/stream")
def stream_message(
    session_id: UUID,
    request: ChatStreamMessageRequest,
    app_user: Annotated[AppUser, Depends(get_current_app_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rag_service: Annotated[RAGOrchestrationService, Depends(get_rag_orchestration_service)],
    title_generator: Annotated[ChatTitleGenerator, Depends(get_chat_title_generator)],
    db: Annotated[Session, Depends(get_db_session)],
) -> StreamingResponse:
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

    db.commit()

    return StreamingResponse(
        _stream_chat_events(
            db=db,
            app_user=app_user,
            session_id=session_id,
            user_message_id=user_message.id,
            current_message=request.content,
            rag_service=rag_service,
        ),
        media_type="text/event-stream",
    )


async def _stream_chat_events(
    *,
    db: Session,
    app_user: AppUser,
    session_id: UUID,
    user_message_id: UUID,
    current_message: str,
    rag_service: RAGOrchestrationService,
) -> AsyncIterator[str]:
    try:
        result = None
        async for event in rag_service.generate_stream(
            db=db,
            session_id=session_id,
            current_message=current_message,
            current_message_id=user_message_id,
        ):
            if isinstance(event, RAGOrchestrationStreamDelta):
                yield _sse_event("delta", {"text": event.text})
            elif isinstance(event, RAGOrchestrationStreamFinal):
                result = event.result

        if result is None:
            raise RuntimeError("Chat generation completed without a final event.")

        assistant_message = append_assistant_message_with_sources(
            db=db,
            app_user=app_user,
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
        final = ChatStreamFinalEvent(
            assistant_message_id=assistant_message.id,
            session_id=session_id,
            sources=assistant_message.sources,
            model=result.model,
            usage=result.usage,
        )
        yield _sse_event("final", final.model_dump(mode="json"))
    except Exception:
        logger.exception("Chat stream generation failed for session %s", session_id)
        db.rollback()
        error = ChatStreamErrorEvent(message="Chat generation failed.", retryable=True)
        yield _sse_event("error", error.model_dump(mode="json"))


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
