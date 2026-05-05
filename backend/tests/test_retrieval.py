from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.app_user import AppUser
from app.models.rag import Document, DocumentChunk, DocumentEmbedding
from app.retrieval.service import retrieve_relevant_chunks


@pytest.fixture
def db_session(migrated_database: Engine) -> Iterator[Session]:
    session_factory = sessionmaker(bind=migrated_database, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


def test_retrieval_returns_only_completed_document_chunks(db_session: Session) -> None:
    provider = FakeEmbeddingProvider()
    completed_chunk = create_embedded_chunk(
        db_session,
        status="completed",
        text="alpha completed source",
        embedding=provider.embed_query("alpha"),
    )
    create_embedded_chunk(
        db_session,
        status="processing",
        text="alpha processing source",
        embedding=provider.embed_query("alpha"),
    )
    create_embedded_chunk(
        db_session,
        status="failed",
        text="alpha failed source",
        embedding=provider.embed_query("alpha"),
    )

    results = retrieve_relevant_chunks(
        db=db_session,
        embedding_provider=provider,
        query="alpha",
        top_k=5,
        min_similarity=0.7,
    )

    assert [result.chunk_id for result in results] == [completed_chunk]


def test_retrieval_excludes_tombstoned_documents(db_session: Session) -> None:
    provider = FakeEmbeddingProvider()
    active_chunk = create_embedded_chunk(
        db_session,
        status="completed",
        text="alpha active source",
        embedding=provider.embed_query("alpha"),
    )
    create_embedded_chunk(
        db_session,
        status="completed",
        text="alpha deleted source",
        embedding=provider.embed_query("alpha"),
        deleted_at=datetime.now(UTC),
    )

    results = retrieve_relevant_chunks(
        db=db_session,
        embedding_provider=provider,
        query="alpha",
        top_k=5,
        min_similarity=0.7,
    )

    assert [result.chunk_id for result in results] == [active_chunk]


def test_retrieval_returns_exact_top_k_by_similarity(db_session: Session) -> None:
    provider = FakeEmbeddingProvider()
    best_chunk = create_embedded_chunk(
        db_session,
        status="completed",
        text="alpha strongest source",
        embedding=provider.embed_query("alpha"),
    )
    create_embedded_chunk(
        db_session,
        status="completed",
        text="alpha weaker source",
        embedding=_vector_with_components(first=0.8, second=0.6),
    )

    results = retrieve_relevant_chunks(
        db=db_session,
        embedding_provider=provider,
        query="alpha",
        top_k=1,
        min_similarity=0.7,
    )

    assert [result.chunk_id for result in results] == [best_chunk]
    assert results[0].score == pytest.approx(1.0)


def test_retrieval_applies_min_similarity_as_no_source_policy(db_session: Session) -> None:
    provider = FakeEmbeddingProvider()
    create_embedded_chunk(
        db_session,
        status="completed",
        text="beta source",
        embedding=provider.embed_query("beta"),
    )

    results = retrieve_relevant_chunks(
        db=db_session,
        embedding_provider=provider,
        query="alpha",
        top_k=5,
        min_similarity=0.7,
    )

    assert results == []


def test_retrieval_uses_injected_embedding_provider(db_session: Session) -> None:
    provider = FakeEmbeddingProvider()
    create_embedded_chunk(
        db_session,
        status="completed",
        text="alpha source",
        embedding=provider.embed_query("alpha"),
    )
    provider.embedded_queries.clear()

    retrieve_relevant_chunks(
        db=db_session,
        embedding_provider=provider,
        query="alpha",
        top_k=5,
        min_similarity=0.7,
    )

    assert provider.embedded_queries == ["alpha"]


class FakeEmbeddingProvider:
    model = "test-embedding"

    def __init__(self) -> None:
        self.embedded_queries: list[str] = []

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.embedded_queries.append(text)
        normalized = text.lower()
        if "alpha" in normalized:
            return _unit_vector(0)
        if "beta" in normalized:
            return _unit_vector(1)
        return _unit_vector(2)


def create_embedded_chunk(
    db: Session,
    *,
    status: str,
    text: str,
    embedding: list[float],
    deleted_at: datetime | None = None,
) -> UUID:
    now = datetime.now(UTC)
    user = AppUser(
        id=uuid4(),
        clerk_user_id=f"user_{uuid4().hex}",
        email="reader@example.com",
        first_name=None,
        last_name=None,
        created_at=now,
        updated_at=now,
    )
    document = Document(
        id=uuid4(),
        original_filename="document.txt",
        display_name="document.txt",
        media_type="text/plain",
        file_extension=".txt",
        byte_size=len(text.encode("utf-8")),
        sha256=sha256(text.encode("utf-8")).hexdigest(),
        object_bucket="test-bucket",
        object_key=f"documents/originals/{uuid4().hex}.txt",
        status=status,
        uploaded_by_app_user_id=user.id,
        created_at=now,
        updated_at=now,
        deleted_at=deleted_at,
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=0,
        text=text,
        token_count=len(text.split()),
        page_number=None,
        section_title=None,
        chunk_metadata={},
        created_at=now,
    )
    db.add_all(
        [
            user,
            document,
            chunk,
            DocumentEmbedding(
                id=uuid4(),
                chunk_id=chunk.id,
                embedding_model="test-embedding",
                embedding=embedding,
                created_at=now,
            ),
        ]
    )
    db.commit()
    return chunk.id


def _unit_vector(index: int) -> list[float]:
    embedding = [0.0] * 1536
    embedding[index] = 1.0
    return embedding


def _vector_with_components(*, first: float, second: float) -> list[float]:
    embedding = [0.0] * 1536
    embedding[0] = first
    embedding[1] = second
    return embedding
