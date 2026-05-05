from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.chat.service import EmptyChatMessageError, append_chat_message
from app.models.app_user import AppUser
from app.models.rag import ChatMessage, Document, DocumentChunk, MessageSource


@pytest.fixture
def auth_headers(make_clerk_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_clerk_token()}"}


def test_chat_sessions_require_auth_without_creating_local_user(
    client: TestClient,
    migrated_database: Engine,
) -> None:
    response = client.post("/api/chat/sessions")

    assert response.status_code == 401
    assert table_count(migrated_database, "app_users") == 0


def test_delete_chat_session_requires_auth_without_creating_local_user(
    client: TestClient,
    migrated_database: Engine,
) -> None:
    response = client.delete(f"/api/chat/sessions/{uuid4()}")

    assert response.status_code == 401
    assert table_count(migrated_database, "app_users") == 0


def test_create_and_load_chat_session_for_current_user(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    create_response = client.post("/api/chat/sessions", headers=auth_headers)

    assert create_response.status_code == 201
    created = create_response.json()
    assert created | {"id": created["id"]} == {
        "id": created["id"],
        "title": "New chat",
        "title_status": "pending",
        "created_at": created["created_at"],
        "updated_at": created["updated_at"],
        "last_message_at": None,
        "messages": [],
    }
    UUID(created["id"])

    load_response = client.get(f"/api/chat/sessions/{created['id']}", headers=auth_headers)

    assert load_response.status_code == 200
    assert load_response.json() == created
    assert table_count(migrated_database, "chat_sessions") == 1


def test_list_sessions_is_user_owned_ordered_by_most_recent_activity(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    first_headers = {"Authorization": f"Bearer {make_clerk_token(sub='user_first')}"}
    other_headers = {
        "Authorization": f"Bearer {make_clerk_token(sub='user_other', email='other@example.com')}"
    }
    older = client.post("/api/chat/sessions", headers=first_headers).json()
    newest_without_message = client.post("/api/chat/sessions", headers=first_headers).json()
    client.post("/api/chat/sessions", headers=other_headers)

    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_first")
        message = append_chat_message(
            db=db,
            app_user=app_user,
            session_id=UUID(older["id"]),
            role="user",
            content="What changed in the quarterly risk notes?",
            chat_model="test-model",
            title_generator=StaticTitleGenerator("Quarterly risk notes"),
        )
        assert message is not None
        db.commit()

    response = client.get("/api/chat/sessions", headers=first_headers)

    assert response.status_code == 200
    sessions = response.json()
    assert [session["id"] for session in sessions] == [older["id"], newest_without_message["id"]]
    assert sessions[0]["last_message"]["content"] == "What changed in the quarterly risk notes?"


def test_cross_user_session_load_returns_not_found(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    owner_headers = {"Authorization": f"Bearer {make_clerk_token(sub='owner')}"}
    intruder_headers = {
        "Authorization": f"Bearer {make_clerk_token(sub='intruder', email='intruder@example.com')}"
    }
    session = client.post("/api/chat/sessions", headers=owner_headers).json()

    response = client.get(f"/api/chat/sessions/{session['id']}", headers=intruder_headers)

    assert response.status_code == 404
    assert table_count(migrated_database, "chat_sessions") == 1


def test_cross_user_session_delete_returns_not_found(
    client: TestClient,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    owner_headers = {"Authorization": f"Bearer {make_clerk_token(sub='owner')}"}
    intruder_headers = {
        "Authorization": f"Bearer {make_clerk_token(sub='intruder', email='intruder@example.com')}"
    }
    session = client.post("/api/chat/sessions", headers=owner_headers).json()

    response = client.delete(f"/api/chat/sessions/{session['id']}", headers=intruder_headers)

    assert response.status_code == 404
    assert table_count(migrated_database, "chat_sessions") == 1


def test_missing_chat_session_delete_returns_not_found(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    response = client.delete(f"/api/chat/sessions/{uuid4()}", headers=auth_headers)

    assert response.status_code == 404


def test_delete_chat_session_removes_owned_session_from_list_and_load(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    session = client.post("/api/chat/sessions", headers=auth_headers).json()

    response = client.delete(f"/api/chat/sessions/{session['id']}", headers=auth_headers)

    assert response.status_code == 204
    assert response.content == b""
    load_response = client.get(f"/api/chat/sessions/{session['id']}", headers=auth_headers)
    assert load_response.status_code == 404
    assert client.get("/api/chat/sessions", headers=auth_headers).json() == []


def test_delete_chat_session_removes_messages_and_sources(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    session_id = UUID(client.post("/api/chat/sessions", headers=auth_headers).json()["id"])

    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_2abc123")
        message = ChatMessage(
            id=uuid4(),
            session_id=session_id,
            role="assistant",
            content="The policy says escalation happens within two days.",
            status="completed",
            model="test-chat-model",
            retrieval_query="escalation windows",
            usage={"input_tokens": 12},
            created_at=datetime.now(UTC),
        )
        document = make_completed_document(app_user)
        chunk = DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            chunk_index=0,
            text="Escalation happens within two days.",
            token_count=6,
            page_number=3,
            section_title="Escalation",
            chunk_metadata={},
            created_at=datetime.now(UTC),
        )
        source = MessageSource(
            id=uuid4(),
            message_id=message.id,
            document_id=document.id,
            document_name=document.display_name,
            chunk_id=chunk.id,
            rank=1,
            score=0.91,
            excerpt="Escalation happens within two days.",
            page_number=3,
            section_title="Escalation",
        )
        db.add_all([message, document, chunk, source])
        db.commit()

    response = client.delete(f"/api/chat/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 204
    assert table_count(migrated_database, "message_sources") == 0
    assert table_count(migrated_database, "chat_messages") == 0
    assert table_count(migrated_database, "chat_sessions") == 0


def test_append_first_user_message_persists_message_and_generated_title(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    session_id = UUID(client.post("/api/chat/sessions", headers=auth_headers).json()["id"])

    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_2abc123")
        message = append_chat_message(
            db=db,
            app_user=app_user,
            session_id=session_id,
            role="user",
            content="Please summarize the onboarding guide",
            chat_model="test-chat-model",
            title_generator=StaticTitleGenerator(
                "Onboarding guide", expected_model="test-chat-model"
            ),
        )
        db.commit()

    assert message is not None
    assert message.role == "user"
    assert message.status == "completed"
    assert message.created_at is not None

    response = client.get(f"/api/chat/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Onboarding guide"
    assert body["title_status"] == "generated"
    assert body["messages"][0]["content"] == "Please summarize the onboarding guide"


def test_append_first_user_message_uses_deterministic_fallback_when_title_generation_fails(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    session_id = UUID(client.post("/api/chat/sessions", headers=auth_headers).json()["id"])
    first_message = "   Explain   escalation windows.   "

    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_2abc123")
        append_chat_message(
            db=db,
            app_user=app_user,
            session_id=session_id,
            role="user",
            content=first_message,
            chat_model="test-chat-model",
            title_generator=FailingTitleGenerator(),
        )
        db.commit()

    response = client.get(f"/api/chat/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["title"] == "Explain escalation windows."
    assert response.json()["title_status"] == "fallback"


def test_append_rejects_empty_messages_without_updating_session(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    session_id = UUID(client.post("/api/chat/sessions", headers=auth_headers).json()["id"])

    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_2abc123")
        with pytest.raises(EmptyChatMessageError):
            append_chat_message(
                db=db,
                app_user=app_user,
                session_id=session_id,
                role="user",
                content="   ",
                chat_model="test-chat-model",
            )
        db.rollback()

    response = client.get(f"/api/chat/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["messages"] == []


def test_load_session_returns_persisted_message_sources(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    session_id = UUID(client.post("/api/chat/sessions", headers=auth_headers).json()["id"])

    with Session(migrated_database) as db:
        app_user = app_user_by_clerk_id(db, "user_2abc123")
        assistant_message = append_chat_message(
            db=db,
            app_user=app_user,
            session_id=session_id,
            role="assistant",
            content="The policy says escalation happens within two days.",
            chat_model="test-chat-model",
            model="test-chat-model",
        )
        assert assistant_message is not None
        document = make_completed_document(app_user)
        chunk = DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            chunk_index=0,
            text="Escalation happens within two days.",
            token_count=6,
            page_number=3,
            section_title="Escalation",
            chunk_metadata={},
            created_at=datetime.now(UTC),
        )
        db.add_all([document, chunk])
        db.add(
            MessageSource(
                id=uuid4(),
                message_id=assistant_message.id,
                document_id=document.id,
                document_name=document.display_name,
                chunk_id=chunk.id,
                rank=1,
                score=0.91,
                excerpt="Escalation happens within two days.",
                page_number=3,
                section_title="Escalation",
            )
        )
        db.commit()

    response = client.get(f"/api/chat/sessions/{session_id}", headers=auth_headers)

    assert response.status_code == 200
    source = response.json()["messages"][0]["sources"][0]
    stable_source = source | {
        "id": source["id"],
        "document_id": source["document_id"],
        "chunk_id": source["chunk_id"],
    }
    assert stable_source == {
        "id": source["id"],
        "document_id": source["document_id"],
        "document_name": "policy.txt",
        "chunk_id": source["chunk_id"],
        "rank": 1,
        "score": 0.91,
        "excerpt": "Escalation happens within two days.",
        "page_number": 3,
        "section_title": "Escalation",
        "document_deleted_at": None,
    }


def app_user_by_clerk_id(db: Session, clerk_user_id: str) -> AppUser:
    return db.execute(select(AppUser).where(AppUser.clerk_user_id == clerk_user_id)).scalar_one()


def make_completed_document(app_user: AppUser) -> Document:
    now = datetime.now(UTC)
    return Document(
        id=uuid4(),
        original_filename="policy.txt",
        display_name="policy.txt",
        media_type="text/plain",
        file_extension=".txt",
        byte_size=39,
        sha256="not-a-real-sha",
        object_bucket="test-bucket",
        object_key=f"documents/originals/{uuid4().hex}.txt",
        status="completed",
        uploaded_by_app_user_id=app_user.id,
        created_at=now,
        updated_at=now,
    )


def table_count(engine: Engine, table_name: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()


class StaticTitleGenerator:
    def __init__(self, title: str, expected_model: str | None = None) -> None:
        self.title = title
        self.expected_model = expected_model

    def generate_title(self, *, first_message: str, model: str) -> str:
        assert first_message
        if self.expected_model is not None:
            assert model == self.expected_model
        return self.title


class FailingTitleGenerator:
    def generate_title(self, *, first_message: str, model: str) -> str:
        raise RuntimeError("model unavailable")
