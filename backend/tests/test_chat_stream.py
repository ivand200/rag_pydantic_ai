from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.chat import get_chat_title_generator, get_rag_orchestration_service
from app.chat.rag_orchestration import (
    PydanticAIAnswerService,
    PydanticAIQueryRewriteService,
    RAGOrchestrationResult,
    RAGOrchestrationService,
    RAGOrchestrationStreamDelta,
    RAGOrchestrationStreamFinal,
    SourceCitationPayload,
)
from app.models.app_user import AppUser
from app.models.rag import ChatMessage, Document, DocumentChunk, DocumentEmbedding, MessageSource


def test_stream_success_emits_final_metadata_and_persists_assistant_sources(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    headers = {"Authorization": f"Bearer {make_clerk_token()}"}
    session_id = UUID(client.post("/api/chat/sessions", headers=headers).json()["id"])
    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_2abc123")
        document, chunk = create_completed_document_chunk(
            db,
            app_user=app_user,
            text="Escalation must happen within two days.",
        )
        document_id = document.id
        document_name = document.display_name
        chunk_id = chunk.id
        db.commit()
    client.app.dependency_overrides[get_rag_orchestration_service] = lambda: StaticRAGService(
        RAGOrchestrationResult(
            answer="Escalation must happen within two days.",
            retrieval_query="escalation deadline",
            sources=[
                SourceCitationPayload(
                    document_id=document_id,
                    document_name=document_name,
                    chunk_id=chunk_id,
                    excerpt="Escalation must happen within two days.",
                    rank=1,
                    score=0.93,
                    page_number=2,
                    section_title="Escalation",
                )
            ],
            model="test-chat-model",
            usage={"requests": 1},
        ),
        deltas=["Escalation must happen ", "within two days."],
    )
    client.app.dependency_overrides[get_chat_title_generator] = lambda: StaticTitleGenerator(
        "Escalation deadline"
    )

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages/stream",
        headers=headers,
        json={"content": "When does escalation happen?"},
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse_events(response.text)
    assert [event["event"] for event in events] == ["delta", "delta", "final"]
    assert events[0]["data"] == {"text": "Escalation must happen "}
    assert events[1]["data"] == {"text": "within two days."}
    final = events[2]["data"]
    assert final | {"assistant_message_id": final["assistant_message_id"]} == {
        "assistant_message_id": final["assistant_message_id"],
        "session_id": str(session_id),
        "model": "test-chat-model",
        "usage": {"requests": 1},
        "sources": [
            {
                "id": final["sources"][0]["id"],
                "document_id": str(document_id),
                "document_name": document_name,
                "chunk_id": str(chunk_id),
                "rank": 1,
                "score": 0.93,
                "excerpt": "Escalation must happen within two days.",
                "page_number": 2,
                "section_title": "Escalation",
                "document_deleted_at": None,
            }
        ],
    }

    with Session(migrated_database) as db:
        messages = db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.role)
        ).scalars()
        assert sorted(message.role for message in messages) == ["assistant", "user"]
        source = db.execute(select(MessageSource)).scalar_one()
        assert source.document_name == document_name


def test_stream_real_orchestration_model_double_answers_through_api(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    headers = {"Authorization": f"Bearer {make_clerk_token()}"}
    session_id = UUID(client.post("/api/chat/sessions", headers=headers).json()["id"])
    embedding_provider = StaticEmbeddingProvider()
    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_2abc123")
        document, chunk = create_completed_document_chunk(
            db,
            app_user=app_user,
            text="April invoice number is INV-98210dmyy-2026-8.",
        )
        db.add(
            DocumentEmbedding(
                id=uuid4(),
                chunk_id=chunk.id,
                embedding_model=embedding_provider.model,
                embedding=embedding_provider.embed_query("April invoice number"),
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
        document_id = document.id
    client.app.dependency_overrides[get_rag_orchestration_service] = lambda: (
        RAGOrchestrationService(
            embedding_provider=embedding_provider,
            query_rewriter=PydanticAIQueryRewriteService(
                model=TestModel(custom_output_args={"query": "April invoice number"})
            ),
            answer_generator=PydanticAIAnswerService(
                model=TestModel(
                    custom_output_text="The April invoice number is INV-98210dmyy-2026-8."
                )
            ),
            chat_model="test-chat-model",
            top_k=1,
            min_similarity=0.7,
        )
    )
    client.app.dependency_overrides[get_chat_title_generator] = lambda: StaticTitleGenerator(
        "April invoice"
    )

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages/stream",
        headers=headers,
        json={"content": "What is April invoice number?"},
    )

    client.app.dependency_overrides.clear()
    events = parse_sse_events(response.text)
    assert "error" not in [event["event"] for event in events]
    assert events[-1]["data"]["sources"][0]["document_id"] == str(document_id)


def test_stream_no_source_persists_completed_assistant_without_citations(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    headers = {"Authorization": f"Bearer {make_clerk_token()}"}
    session_id = UUID(client.post("/api/chat/sessions", headers=headers).json()["id"])
    client.app.dependency_overrides[get_rag_orchestration_service] = lambda: StaticRAGService(
        RAGOrchestrationResult(
            answer="I could not find relevant sources in the uploaded documents to answer that.",
            retrieval_query="unknown policy",
            sources=[],
            model="test-chat-model",
            usage=None,
        )
    )
    client.app.dependency_overrides[get_chat_title_generator] = lambda: StaticTitleGenerator(
        "Unknown policy"
    )

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages/stream",
        headers=headers,
        json={"content": "Can you answer this from the docs?"},
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    events = parse_sse_events(response.text)
    assert [event["event"] for event in events] == ["delta", "final"]
    assert events[1]["data"]["sources"] == []

    with Session(migrated_database) as db:
        assistant = db.execute(
            select(ChatMessage).where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "assistant",
            )
        ).scalar_one()
        assert assistant.status == "completed"
        assert db.execute(select(func.count()).select_from(MessageSource)).scalar_one() == 0


def test_stream_failure_emits_error_without_persisting_assistant_message(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    headers = {"Authorization": f"Bearer {make_clerk_token()}"}
    session_id = UUID(client.post("/api/chat/sessions", headers=headers).json()["id"])
    client.app.dependency_overrides[get_rag_orchestration_service] = lambda: FailingRAGService()
    client.app.dependency_overrides[get_chat_title_generator] = lambda: StaticTitleGenerator(
        "Model failure"
    )

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages/stream",
        headers=headers,
        json={"content": "Trigger a model failure."},
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert parse_sse_events(response.text) == [
        {"event": "error", "data": {"message": "Chat generation failed.", "retryable": True}}
    ]

    with Session(migrated_database) as db:
        roles = db.execute(
            select(ChatMessage.role).where(ChatMessage.session_id == session_id)
        ).scalars()
        assert list(roles) == ["user"]


def test_stream_persistence_failure_rolls_back_partial_assistant_and_sources(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    headers = {"Authorization": f"Bearer {make_clerk_token()}"}
    session_id = UUID(client.post("/api/chat/sessions", headers=headers).json()["id"])
    client.app.dependency_overrides[get_rag_orchestration_service] = lambda: StaticRAGService(
        RAGOrchestrationResult(
            answer="This answer cannot be committed with its invalid source.",
            retrieval_query="invalid source",
            sources=[
                SourceCitationPayload(
                    document_id=uuid4(),
                    document_name="missing.txt",
                    chunk_id=uuid4(),
                    excerpt="Missing source.",
                    rank=1,
                    score=0.91,
                )
            ],
            model="test-chat-model",
            usage=None,
        )
    )
    client.app.dependency_overrides[get_chat_title_generator] = lambda: StaticTitleGenerator(
        "Invalid source"
    )

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages/stream",
        headers=headers,
        json={"content": "Trigger a source persistence failure."},
    )

    client.app.dependency_overrides.clear()
    assert parse_sse_events(response.text) == [
        {
            "event": "delta",
            "data": {"text": "This answer cannot be committed with its invalid source."},
        },
        {"event": "error", "data": {"message": "Chat generation failed.", "retryable": True}},
    ]
    with Session(migrated_database) as db:
        roles = db.execute(
            select(ChatMessage.role).where(ChatMessage.session_id == session_id)
        ).scalars()
        assert list(roles) == ["user"]
        assert db.execute(select(func.count()).select_from(MessageSource)).scalar_one() == 0


def test_stream_cross_user_append_returns_not_found_without_message(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    owner_headers = {"Authorization": f"Bearer {make_clerk_token(sub='owner')}"}
    intruder_headers = {
        "Authorization": f"Bearer {make_clerk_token(sub='intruder', email='intruder@example.com')}"
    }
    session_id = client.post("/api/chat/sessions", headers=owner_headers).json()["id"]
    client.app.dependency_overrides[get_rag_orchestration_service] = lambda: FailingRAGService()
    client.app.dependency_overrides[get_chat_title_generator] = lambda: StaticTitleGenerator(
        "Cross user"
    )

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages/stream",
        headers=intruder_headers,
        json={"content": "Append to someone else's session."},
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 404
    with Session(migrated_database) as db:
        assert db.execute(select(func.count()).select_from(ChatMessage)).scalar_one() == 0


def test_stream_first_user_message_uses_model_title_generator(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    headers = {"Authorization": f"Bearer {make_clerk_token()}"}
    session_id = UUID(client.post("/api/chat/sessions", headers=headers).json()["id"])
    client.app.dependency_overrides[get_rag_orchestration_service] = lambda: StaticRAGService(
        RAGOrchestrationResult(
            answer="I could not find relevant sources in the uploaded documents to answer that.",
            retrieval_query="onboarding guide",
            sources=[],
            model="test-chat-model",
            usage=None,
        )
    )
    client.app.dependency_overrides[get_chat_title_generator] = lambda: StaticTitleGenerator(
        "Onboarding Guide Review",
        expected_model="gpt-5.4-mini",
    )

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages/stream",
        headers=headers,
        json={"content": "Please summarize the onboarding guide."},
    )

    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert [event["event"] for event in parse_sse_events(response.text)] == ["delta", "final"]

    load_response = client.get(f"/api/chat/sessions/{session_id}", headers=headers)

    assert load_response.status_code == 200
    body = load_response.json()
    assert body["title"] == "Onboarding Guide Review"
    assert body["title_status"] == "generated"


def parse_sse_events(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for raw_event in text.strip().split("\n\n"):
        lines = raw_event.splitlines()
        event_name = next(
            line.removeprefix("event: ") for line in lines if line.startswith("event: ")
        )
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append({"event": event_name, "data": json.loads(data)})
    return events


def app_user_by_clerk_id(db: Session, clerk_user_id: str) -> AppUser:
    return db.execute(select(AppUser).where(AppUser.clerk_user_id == clerk_user_id)).scalar_one()


def create_completed_document_chunk(
    db: Session,
    *,
    app_user: AppUser,
    text: str,
) -> tuple[Document, DocumentChunk]:
    now = datetime.now(UTC)
    document = Document(
        id=uuid4(),
        original_filename="policy.txt",
        display_name="policy.txt",
        media_type="text/plain",
        file_extension=".txt",
        byte_size=len(text.encode("utf-8")),
        sha256=sha256(text.encode("utf-8")).hexdigest(),
        object_bucket="test-bucket",
        object_key=f"documents/originals/{uuid4().hex}.txt",
        status="completed",
        uploaded_by_app_user_id=app_user.id,
        created_at=now,
        updated_at=now,
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=0,
        text=text,
        token_count=len(text.split()),
        page_number=2,
        section_title="Escalation",
        chunk_metadata={},
        created_at=now,
    )
    db.add_all([document, chunk])
    db.flush()
    return document, chunk


class StaticRAGService:
    def __init__(self, result: RAGOrchestrationResult, deltas: list[str] | None = None) -> None:
        self.result = result
        self.deltas = deltas

    async def generate_stream(
        self,
        *,
        db: Session,
        session_id: UUID,
        current_message: str,
        current_message_id: UUID | None = None,
    ) -> AsyncIterator[RAGOrchestrationStreamDelta | RAGOrchestrationStreamFinal]:
        assert db
        assert session_id
        assert current_message
        assert current_message_id
        for delta in self.deltas or [self.result.answer]:
            yield RAGOrchestrationStreamDelta(delta)
        yield RAGOrchestrationStreamFinal(self.result)


class FailingRAGService:
    async def generate_stream(
        self,
        *,
        db: Session,
        session_id: UUID,
        current_message: str,
        current_message_id: UUID | None = None,
    ) -> AsyncIterator[RAGOrchestrationStreamDelta | RAGOrchestrationStreamFinal]:
        assert db
        assert session_id
        assert current_message
        assert current_message_id
        raise RuntimeError("model unavailable")
        yield RAGOrchestrationStreamDelta("")  # pragma: no cover


class StaticEmbeddingProvider:
    model = "test-embedding"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        assert text
        embedding = [0.0] * 1536
        embedding[0] = 1.0
        return embedding


class StaticTitleGenerator:
    def __init__(self, title: str, expected_model: str | None = None) -> None:
        self.title = title
        self.expected_model = expected_model

    def generate_title(self, *, first_message: str, model: str) -> str:
        assert first_message
        if self.expected_model is not None:
            assert model == self.expected_model
        return self.title
