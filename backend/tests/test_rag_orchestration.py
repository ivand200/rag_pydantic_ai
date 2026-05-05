from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.chat.rag_orchestration import (
    AnswerStreamDelta,
    AnswerStreamFinal,
    ChatHistoryMessage,
    ChatModelConfigurationError,
    PydanticAIAnswerService,
    PydanticAIQueryRewriteService,
    RAGOrchestrationService,
    RAGOrchestrationStreamDelta,
    RAGOrchestrationStreamFinal,
    build_openai_chat_model,
    build_source_citation_payloads,
    generate_no_source_answer,
)
from app.chat.source_enrichment import MarkdownSectionOutlineEnricher
from app.chat.title_generation import PydanticAIChatTitleGenerator
from app.core.config import Settings
from app.models.app_user import AppUser
from app.models.rag import ChatMessage, ChatSession, Document, DocumentChunk, DocumentEmbedding
from app.retrieval.service import RetrievalResult


@pytest.fixture
def db_session(migrated_database: Engine) -> Iterator[Session]:
    session_factory = sessionmaker(bind=migrated_database, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


def test_query_rewrite_uses_pydantic_ai_model_double() -> None:
    service = PydanticAIQueryRewriteService(
        model=TestModel(custom_output_args={"query": "quarterly risk escalation policy"})
    )

    query = service.rewrite(
        current_message="What changed there?",
        history=[ChatHistoryMessage(role="user", content="Open the quarterly risk notes.")],
    )

    assert query == "quarterly risk escalation policy"


def test_answer_generation_uses_pydantic_ai_model_double() -> None:
    service = PydanticAIAnswerService(
        model=TestModel(custom_output_args={"answer": "Escalation must happen within two days."})
    )

    answer, usage = service.answer(
        current_message="When does escalation happen?",
        history=[],
        sources=[make_retrieval_result(text="Escalation must happen within two days.")],
    )

    assert answer == "Escalation must happen within two days."
    assert usage is not None and usage["requests"] == 1


def test_answer_generation_streams_text_deltas_with_pydantic_ai_model_double() -> None:
    service = PydanticAIAnswerService(
        model=TestModel(custom_output_text="Escalation must happen within two days.")
    )

    events = asyncio.run(
        collect_answer_events(
            service.stream_answer(
                current_message="When does escalation happen?",
                history=[],
                sources=[make_retrieval_result(text="Escalation must happen within two days.")],
            )
        )
    )

    deltas = [event.text for event in events if isinstance(event, AnswerStreamDelta)]
    final = next(event for event in events if isinstance(event, AnswerStreamFinal))
    assert "".join(deltas) == "Escalation must happen within two days."
    assert len(deltas) > 1
    assert final.usage is not None and final.usage["requests"] == 1


def test_title_generation_uses_pydantic_ai_model_double() -> None:
    service = PydanticAIChatTitleGenerator(
        model=TestModel(custom_output_args={"title": "Escalation Policy Review"})
    )

    title = service.generate_title(
        first_message="Please summarize the escalation policy.",
        model="test-chat-model",
    )

    assert title == "Escalation Policy Review"


def test_orchestration_uses_current_message_plus_last_six_same_session_messages(
    db_session: Session,
) -> None:
    provider = FakeEmbeddingProvider()
    session = create_session_with_messages(db_session, prior_message_count=7)
    current_message = ChatMessage(
        id=uuid4(),
        session_id=session.id,
        role="user",
        content="What is the escalation deadline?",
        status="completed",
        created_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(current_message)
    create_embedded_chunk(
        db_session,
        app_user_id=session.app_user_id,
        text="Escalation deadline is two days.",
        embedding=provider.embed_query("escalation deadline"),
    )
    db_session.commit()
    rewriter = RecordingQueryRewriter("escalation deadline")
    answerer = RecordingAnswerGenerator("Escalation deadline is two days.")
    service = RAGOrchestrationService(
        embedding_provider=provider,
        query_rewriter=rewriter,
        answer_generator=answerer,
        chat_model="test-chat-model",
        top_k=5,
        min_similarity=0.7,
    )

    result = service.generate(
        db=db_session,
        session_id=session.id,
        current_message=current_message.content,
        current_message_id=current_message.id,
    )

    assert result.answer == "Escalation deadline is two days."
    assert [message.content for message in rewriter.seen_history] == [
        "message 1",
        "message 2",
        "message 3",
        "message 4",
        "message 5",
        "message 6",
    ]
    assert answerer.seen_current_message == "What is the escalation deadline?"


def test_orchestration_generates_no_source_response_without_answer_model(
    db_session: Session,
) -> None:
    session = create_session_with_messages(db_session, prior_message_count=1)
    db_session.commit()
    service = RAGOrchestrationService(
        embedding_provider=FakeEmbeddingProvider(),
        query_rewriter=RecordingQueryRewriter("unknown topic"),
        answer_generator=FailingAnswerGenerator(),
        chat_model="test-chat-model",
        top_k=5,
        min_similarity=0.7,
    )

    result = service.generate(
        db=db_session,
        session_id=session.id,
        current_message="Can uploaded docs answer this?",
    )

    assert result.answer == generate_no_source_answer()
    assert result.sources == []


def test_orchestration_enriches_sources_before_answer_and_citation_payloads(
    db_session: Session,
) -> None:
    provider = FakeEmbeddingProvider()
    session = create_session_with_messages(db_session, prior_message_count=0)
    create_embedded_chunk(
        db_session,
        app_user_id=session.app_user_id,
        text="The component docs include accordion and alert.",
        embedding=provider.embed_query("DaisyUI components"),
    )
    db_session.commit()
    answerer = RecordingAnswerGenerator("DaisyUI has 2 components in the uploaded document.")
    enricher = RecordingSourceEnricher()
    service = RAGOrchestrationService(
        embedding_provider=provider,
        query_rewriter=RecordingQueryRewriter("DaisyUI components"),
        answer_generator=answerer,
        chat_model="test-chat-model",
        top_k=1,
        min_similarity=0.7,
        source_enricher=enricher,
    )

    result = service.generate(
        db=db_session,
        session_id=session.id,
        current_message="How many components does DaisyUI have?",
    )

    assert enricher.seen_retrieval_query == "DaisyUI components"
    assert answerer.seen_sources[0].section_title == "Derived document outline"
    assert "Item count: 2" in answerer.seen_sources[0].text
    assert result.sources[0].section_title == "Derived document outline"


def test_orchestration_streams_answer_deltas_before_final(
    db_session: Session,
) -> None:
    provider = FakeEmbeddingProvider()
    session = create_session_with_messages(db_session, prior_message_count=0)
    create_embedded_chunk(
        db_session,
        app_user_id=session.app_user_id,
        text="Escalation deadline is two days.",
        embedding=provider.embed_query("escalation deadline"),
    )
    db_session.commit()
    service = RAGOrchestrationService(
        embedding_provider=provider,
        query_rewriter=RecordingQueryRewriter("escalation deadline"),
        answer_generator=RecordingAnswerGenerator(
            "Escalation deadline is two days.",
            stream_deltas=["Escalation deadline ", "is two days."],
        ),
        chat_model="test-chat-model",
        top_k=5,
        min_similarity=0.7,
    )

    events = asyncio.run(
        collect_stream_events(
            service.generate_stream(
                db=db_session,
                session_id=session.id,
                current_message="When is the escalation deadline?",
            )
        )
    )

    assert [event.text for event in events if isinstance(event, RAGOrchestrationStreamDelta)] == [
        "Escalation deadline ",
        "is two days.",
    ]
    final = next(event for event in events if isinstance(event, RAGOrchestrationStreamFinal))
    assert final.result.answer == "Escalation deadline is two days."
    assert final.result.usage == {"requests": 1}
    assert final.result.sources[0].excerpt == "Escalation deadline is two days."


def test_markdown_section_outline_enricher_counts_headings_from_matching_sections(
    db_session: Session,
) -> None:
    session = create_session_with_messages(db_session, prior_message_count=0)
    document, chunks = create_markdown_outline_document(db_session, app_user_id=session.app_user_id)
    db_session.commit()
    source = make_retrieval_result(
        document_id=document.id,
        document_name=document.display_name,
        chunk_id=chunks[1].id,
        text=chunks[1].text,
        score=0.61,
        section_title=chunks[1].section_title,
    )
    enricher = MarkdownSectionOutlineEnricher()

    enriched = enricher.enrich(
        db=db_session,
        current_message="How many components does DaisyUI have?",
        retrieval_query="How many components does DaisyUI have?",
        sources=[source],
    )

    assert enriched[0].section_title == "Derived document outline"
    assert "Matching section: daisyUI 5 components" in enriched[0].text
    assert "Item count: 3" in enriched[0].text
    assert "accordion, alert, badge" in enriched[0].text
    assert "daisyUI color names" not in enriched[0].text


def test_source_citation_payloads_include_document_chunk_rank_score_and_metadata() -> None:
    document_id = uuid4()
    chunk_id = uuid4()
    source = make_retrieval_result(
        document_id=document_id,
        document_name="runbook.md",
        chunk_id=chunk_id,
        text="  Escalation  happens within two days.  ",
        score=0.91,
        page_number=4,
        section_title="Escalation",
    )

    citation = build_source_citation_payloads([source])[0]

    assert citation.model_dump() == {
        "document_id": document_id,
        "document_name": "runbook.md",
        "chunk_id": chunk_id,
        "excerpt": "Escalation happens within two days.",
        "rank": 1,
        "score": 0.91,
        "page_number": 4,
        "section_title": "Escalation",
    }


def test_chat_model_configuration_is_openai_only() -> None:
    with pytest.raises(ChatModelConfigurationError):
        build_openai_chat_model(settings=Settings(openai_api_key=None))

    model = build_openai_chat_model(
        settings=Settings(openai_api_key="test-key", chat_model="gpt-5.4-mini")
    )

    assert isinstance(model, OpenAIChatModel)


class FakeEmbeddingProvider:
    model = "test-embedding"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        if "escalation" in text.lower():
            return unit_vector(0)
        return unit_vector(1)


class RecordingQueryRewriter:
    def __init__(self, query: str) -> None:
        self.query = query
        self.seen_current_message: str | None = None
        self.seen_history: list[ChatHistoryMessage] = []

    def rewrite(
        self,
        *,
        current_message: str,
        history: Sequence[ChatHistoryMessage],
    ) -> str:
        self.seen_current_message = current_message
        self.seen_history = list(history)
        return self.query


class RecordingAnswerGenerator:
    def __init__(self, answer: str, stream_deltas: list[str] | None = None) -> None:
        self.answer_text = answer
        self.stream_deltas = stream_deltas
        self.seen_current_message: str | None = None
        self.seen_sources: list[RetrievalResult] = []

    def answer(
        self,
        *,
        current_message: str,
        history: Sequence[ChatHistoryMessage],
        sources: Sequence[RetrievalResult],
    ) -> tuple[str, dict[str, object] | None]:
        self.seen_current_message = current_message
        self.seen_sources = list(sources)
        return self.answer_text, {"requests": 1}

    async def stream_answer(
        self,
        *,
        current_message: str,
        history: Sequence[ChatHistoryMessage],
        sources: Sequence[RetrievalResult],
    ) -> AsyncIterator[AnswerStreamDelta | AnswerStreamFinal]:
        self.seen_current_message = current_message
        self.seen_sources = list(sources)
        for delta in self.stream_deltas or [self.answer_text]:
            yield AnswerStreamDelta(delta)
        yield AnswerStreamFinal(usage={"requests": 1})


class RecordingSourceEnricher:
    def __init__(self) -> None:
        self.seen_retrieval_query: str | None = None

    def enrich(
        self,
        *,
        db: Session,
        current_message: str,
        retrieval_query: str,
        sources: Sequence[RetrievalResult],
    ) -> list[RetrievalResult]:
        assert db
        assert current_message
        self.seen_retrieval_query = retrieval_query
        first = sources[0]
        derived = RetrievalResult(
            document_id=first.document_id,
            document_name=first.document_name,
            chunk_id=first.chunk_id,
            chunk_index=first.chunk_index,
            text="Item count: 2\nItems:\naccordion, alert",
            score=first.score,
            page_number=first.page_number,
            section_title="Derived document outline",
        )
        return [derived, *sources]


class FailingAnswerGenerator:
    def answer(
        self,
        *,
        current_message: str,
        history: Sequence[ChatHistoryMessage],
        sources: Sequence[RetrievalResult],
    ) -> tuple[str, dict[str, object] | None]:
        raise AssertionError("answer model should not run when no sources are retrieved")

    async def stream_answer(
        self,
        *,
        current_message: str,
        history: Sequence[ChatHistoryMessage],
        sources: Sequence[RetrievalResult],
    ) -> AsyncIterator[AnswerStreamDelta | AnswerStreamFinal]:
        raise AssertionError("answer model should not run when no sources are retrieved")


async def collect_stream_events(
    events: AsyncIterator[RAGOrchestrationStreamDelta | RAGOrchestrationStreamFinal],
) -> list[RAGOrchestrationStreamDelta | RAGOrchestrationStreamFinal]:
    return [event async for event in events]


async def collect_answer_events(
    events: AsyncIterator[AnswerStreamDelta | AnswerStreamFinal],
) -> list[AnswerStreamDelta | AnswerStreamFinal]:
    return [event async for event in events]


def create_session_with_messages(db: Session, *, prior_message_count: int) -> ChatSession:
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
    session = ChatSession(
        id=uuid4(),
        app_user_id=user.id,
        title="New chat",
        title_status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add_all([user, session])
    db.flush()
    for index in range(prior_message_count):
        db.add(
            ChatMessage(
                id=uuid4(),
                session_id=session.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"message {index}",
                status="completed",
                created_at=now + timedelta(minutes=index),
            )
        )
    db.flush()
    return session


def create_embedded_chunk(
    db: Session,
    *,
    app_user_id: UUID,
    text: str,
    embedding: list[float],
) -> None:
    now = datetime.now(UTC)
    document = Document(
        id=uuid4(),
        original_filename="runbook.md",
        display_name="runbook.md",
        media_type="text/markdown",
        file_extension=".md",
        byte_size=len(text.encode("utf-8")),
        sha256=sha256(text.encode("utf-8")).hexdigest(),
        object_bucket="test-bucket",
        object_key=f"documents/originals/{uuid4().hex}.md",
        status="completed",
        uploaded_by_app_user_id=app_user_id,
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
    db.add_all(
        [
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


def create_markdown_outline_document(
    db: Session,
    *,
    app_user_id: UUID,
) -> tuple[Document, list[DocumentChunk]]:
    now = datetime.now(UTC)
    document = Document(
        id=uuid4(),
        original_filename="llms.txt",
        display_name="llms.txt",
        media_type="text/plain",
        file_extension=".txt",
        byte_size=1024,
        sha256=sha256(b"llms").hexdigest(),
        object_bucket="test-bucket",
        object_key=f"documents/originals/{uuid4().hex}.txt",
        status="completed",
        uploaded_by_app_user_id=app_user_id,
        created_at=now,
        updated_at=now,
    )
    chunks = [
        DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            chunk_index=0,
            text="### daisyUI color names\nColors are not components.",
            token_count=6,
            page_number=None,
            section_title="daisyUI 5 colors",
            chunk_metadata={},
            created_at=now,
        ),
        DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            chunk_index=1,
            text="\n".join(
                [
                    "### accordion",
                    "[accordion docs](https://daisyui.com/components/accordion/)",
                    "### alert",
                    "[alert docs](https://daisyui.com/components/alert/)",
                ]
            ),
            token_count=10,
            page_number=None,
            section_title="daisyUI 5 components",
            chunk_metadata={},
            created_at=now,
        ),
        DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            chunk_index=2,
            text="### badge\n[badge docs](https://daisyui.com/components/badge/)",
            token_count=5,
            page_number=None,
            section_title="daisyUI 5 components",
            chunk_metadata={},
            created_at=now,
        ),
    ]
    db.add_all([document, *chunks])
    db.flush()
    return document, chunks


def make_retrieval_result(
    *,
    document_id: UUID | None = None,
    document_name: str = "policy.txt",
    chunk_id: UUID | None = None,
    text: str,
    score: float = 1.0,
    page_number: int | None = None,
    section_title: str | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        document_id=document_id or uuid4(),
        document_name=document_name,
        chunk_id=chunk_id or uuid4(),
        chunk_index=0,
        text=text,
        score=score,
        page_number=page_number,
        section_title=section_title,
    )


def unit_vector(index: int) -> list[float]:
    embedding = [0.0] * 1536
    embedding[index] = 1.0
    return embedding
