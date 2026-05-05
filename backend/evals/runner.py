from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.chat.rag_orchestration import (
    AnswerStreamDelta,
    AnswerStreamFinal,
    ChatHistoryMessage,
    RAGOrchestrationResult,
    RAGOrchestrationService,
    RAGOrchestrationStreamDelta,
    RAGOrchestrationStreamFinal,
    generate_no_source_answer,
)
from app.chat.source_enrichment import (
    MarkdownSectionOutlineEnricher,
    NoOpSourceEnricher,
    SourceEnricher,
)
from app.core.config import get_settings
from app.models.app_user import AppUser
from app.models.rag import ChatMessage, ChatSession, Document, DocumentChunk, DocumentEmbedding
from app.retrieval.service import RetrievalResult


@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvalQualityGroup:
    name: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class SeededFixture:
    app_user: AppUser
    session: ChatSession
    active_document: Document
    active_chunk: DocumentChunk
    deleted_document: Document
    deleted_chunk: DocumentChunk


QUALITY_GROUPS: tuple[EvalQualityGroup, ...] = (
    EvalQualityGroup("Retrieval and grounding", ("retrieval_hit", "aggregate_outline_count")),
    EvalQualityGroup("Citation behavior", ("citation_correctness",)),
    EvalQualityGroup("No-source behavior", ("no_source",)),
    EvalQualityGroup("Deleted-document exclusion", ("deleted_document_exclusion",)),
    EvalQualityGroup("Query rewrite", ("query_rewrite",)),
)


class DeterministicEmbeddingProvider:
    model = "deterministic-eval-embedding"

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text_value: str) -> list[float]:
        normalized = text_value.lower()
        if "escalation" in normalized or "runbook" in normalized:
            return _unit_vector(0)
        if "vacation" in normalized:
            return _unit_vector(1)
        if "daisyui" in normalized or "component" in normalized:
            return _unit_vector(2)
        return _unit_vector(2)


class ScriptedQueryRewriter:
    def __init__(self, retrieval_query: str) -> None:
        self.retrieval_query = retrieval_query
        self.seen_current_message: str | None = None
        self.seen_history: list[ChatHistoryMessage] = []

    async def rewrite(
        self,
        *,
        current_message: str,
        history: Sequence[ChatHistoryMessage],
    ) -> str:
        self.seen_current_message = current_message
        self.seen_history = list(history)
        return self.retrieval_query


class SourceGroundedAnswerGenerator:
    def __init__(self, answer: str) -> None:
        self.answer_text = answer
        self.seen_sources: list[RetrievalResult] = []
        self.call_count = 0

    async def stream_answer(
        self,
        *,
        current_message: str,
        history: Sequence[ChatHistoryMessage],
        sources: Sequence[RetrievalResult],
    ) -> AsyncIterator[AnswerStreamDelta | AnswerStreamFinal]:
        assert current_message
        assert history is not None
        self.call_count += 1
        self.seen_sources = list(sources)
        if not sources:
            raise AssertionError("Answer generation should not run without retrieved sources.")
        yield AnswerStreamDelta(self.answer_text)
        yield AnswerStreamFinal(usage={"requests": 1, "eval": True})


def main() -> int:
    settings = get_settings()
    database_url = settings.test_database_url
    if not database_url:
        print("backend evals require TEST_DATABASE_URL or Settings.test_database_url")
        return 2

    try:
        assert_test_database_url(database_url, settings.database_url)
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        print(f"backend evals could not reach Postgres test database: {exc}")
        return 2
    except ValueError as exc:
        print(f"backend evals refused to run: {exc}")
        return 2

    command.upgrade(Config("alembic.ini"), "head")
    truncate_database(engine)

    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    results: list[EvalResult] = []
    with session_factory() as db:
        fixture = seed_eval_fixture(db)
        results.extend(
            [
                eval_retrieval_hit(db, fixture),
                eval_citation_correctness(db, fixture),
                eval_no_source(db, fixture),
                eval_deleted_document_exclusion(db, fixture),
                eval_query_rewrite(db, fixture),
                eval_aggregate_outline_count(db, fixture),
            ]
        )

    truncate_database(engine)
    engine.dispose()

    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"{marker} {result.name}: {result.detail}")

    print_quality_summary(results)

    failed = [result for result in results if not result.passed]
    if failed:
        print(f"{len(failed)} deterministic eval(s) failed.")
        return 1

    print(f"{len(results)} deterministic evals passed.")
    return 0


def print_quality_summary(results: Sequence[EvalResult]) -> None:
    result_by_name = {result.name: result for result in results}

    print("Quality summary:")
    for group in QUALITY_GROUPS:
        group_results = [result_by_name[name] for name in group.checks if name in result_by_name]
        passed_count = sum(result.passed for result in group_results)
        total_count = len(group_results)
        status = "PASS" if passed_count == total_count else "FAIL"
        check_names = ", ".join(result.name for result in group_results)
        print(f"{status} {group.name}: {passed_count}/{total_count} checks ({check_names})")


def eval_retrieval_hit(db: Session, fixture: SeededFixture) -> EvalResult:
    service = build_eval_service(
        retrieval_query="escalation runbook deadline",
        answer="Escalation deadline is two business days.",
    )

    result = generate_eval_result(
        service=service,
        db=db,
        session_id=fixture.session.id,
        current_message="What is the escalation deadline?",
    )

    passed = [source.chunk_id for source in result.sources] == [fixture.active_chunk.id]
    returned_chunk_ids = [source.chunk_id for source in result.sources]
    return EvalResult(
        name="retrieval_hit",
        passed=passed,
        detail=f"expected active chunk {fixture.active_chunk.id}, got {returned_chunk_ids}",
    )


def eval_citation_correctness(db: Session, fixture: SeededFixture) -> EvalResult:
    service = build_eval_service(
        retrieval_query="escalation runbook deadline",
        answer="Escalation deadline is two business days.",
    )

    result = generate_eval_result(
        service=service,
        db=db,
        session_id=fixture.session.id,
        current_message="Cite the escalation deadline.",
    )

    citation = result.sources[0] if result.sources else None
    passed = (
        citation is not None
        and citation.document_id == fixture.active_document.id
        and citation.chunk_id == fixture.active_chunk.id
        and citation.document_name == "Escalation Runbook.md"
        and citation.rank == 1
        and "two business days" in citation.excerpt
    )
    return EvalResult(
        name="citation_correctness",
        passed=passed,
        detail="citation points at the retrieved active source with expected excerpt"
        if passed
        else f"unexpected citation payload: {citation}",
    )


def eval_no_source(db: Session, fixture: SeededFixture) -> EvalResult:
    answer_generator = SourceGroundedAnswerGenerator("This should not be used.")
    service = build_eval_service(
        retrieval_query="vacation rollover policy",
        answer="This should not be used.",
        answer_generator=answer_generator,
    )

    result = generate_eval_result(
        service=service,
        db=db,
        session_id=fixture.session.id,
        current_message="What is the vacation rollover policy?",
    )

    passed = (
        result.answer == generate_no_source_answer()
        and result.sources == []
        and answer_generator.call_count == 0
    )
    return EvalResult(
        name="no_source",
        passed=passed,
        detail="returned no-source answer without invoking answer generator"
        if passed
        else (
            f"answer={result.answer!r}, sources={result.sources}, "
            f"answer_calls={answer_generator.call_count}"
        ),
    )


def eval_deleted_document_exclusion(db: Session, fixture: SeededFixture) -> EvalResult:
    service = build_eval_service(
        retrieval_query="deleted escalation runbook",
        answer="Only the active source may be cited.",
    )

    result = generate_eval_result(
        service=service,
        db=db,
        session_id=fixture.session.id,
        current_message="Use the deleted escalation runbook.",
    )

    returned_chunk_ids = [source.chunk_id for source in result.sources]
    passed = (
        fixture.active_chunk.id in returned_chunk_ids
        and fixture.deleted_chunk.id not in returned_chunk_ids
    )
    return EvalResult(
        name="deleted_document_exclusion",
        passed=passed,
        detail=(
            f"returned chunks {returned_chunk_ids}; "
            f"deleted chunk {fixture.deleted_chunk.id} excluded"
        ),
    )


def eval_query_rewrite(db: Session, fixture: SeededFixture) -> EvalResult:
    rewriter = ScriptedQueryRewriter("escalation runbook deadline")
    service = build_eval_service(
        retrieval_query="escalation runbook deadline",
        answer="Escalation deadline is two business days.",
        query_rewriter=rewriter,
    )
    current = ChatMessage(
        id=uuid4(),
        session_id=fixture.session.id,
        role="user",
        content="What changed there?",
        status="completed",
        created_at=datetime.now(UTC) + timedelta(minutes=20),
    )
    db.add(current)
    db.commit()

    result = generate_eval_result(
        service=service,
        db=db,
        session_id=fixture.session.id,
        current_message=current.content,
        current_message_id=current.id,
    )

    passed = (
        result.retrieval_query == "escalation runbook deadline"
        and rewriter.seen_current_message == "What changed there?"
        and [message.content for message in rewriter.seen_history]
        == [
            "Open the escalation runbook.",
            "It covers incident deadlines.",
        ]
        and [source.chunk_id for source in result.sources] == [fixture.active_chunk.id]
    )
    return EvalResult(
        name="query_rewrite",
        passed=passed,
        detail="rewrite used recent history and drove retrieval to the active source"
        if passed
        else (
            f"query={result.retrieval_query!r}, history="
            f"{[message.content for message in rewriter.seen_history]}, sources={result.sources}"
        ),
    )


def eval_aggregate_outline_count(db: Session, fixture: SeededFixture) -> EvalResult:
    document, chunks = seed_component_outline_document(db, app_user_id=fixture.app_user.id)
    answer_generator = SourceGroundedAnswerGenerator("DaisyUI has 65 components.")
    service = build_eval_service(
        retrieval_query="How many components does DaisyUI have?",
        answer="DaisyUI has 65 components.",
        answer_generator=answer_generator,
        source_enricher=MarkdownSectionOutlineEnricher(),
    )

    result = generate_eval_result(
        service=service,
        db=db,
        session_id=fixture.session.id,
        current_message="How much components in DaisyUI?",
    )

    first_answer_source = (
        answer_generator.seen_sources[0] if answer_generator.seen_sources else None
    )
    first_citation = result.sources[0] if result.sources else None
    passed = (
        first_answer_source is not None
        and first_answer_source.document_id == document.id
        and first_answer_source.chunk_id == chunks[0].id
        and first_answer_source.section_title == "Derived document outline"
        and "Matching section: daisyUI 5 components" in first_answer_source.text
        and "Item count: 65" in first_answer_source.text
        and "accordion, alert, avatar" in first_answer_source.text
        and first_citation is not None
        and first_citation.section_title == "Derived document outline"
        and "Item count: 65" in first_citation.excerpt
    )
    return EvalResult(
        name="aggregate_outline_count",
        passed=passed,
        detail="derived component count evidence was passed to the answer path"
        if passed
        else (
            f"first_answer_source={first_answer_source}, first_citation={first_citation}, "
            f"returned_sources={result.sources}"
        ),
    )


def build_eval_service(
    *,
    retrieval_query: str,
    answer: str,
    query_rewriter: ScriptedQueryRewriter | None = None,
    answer_generator: SourceGroundedAnswerGenerator | None = None,
    source_enricher: SourceEnricher | None = None,
) -> RAGOrchestrationService:
    return RAGOrchestrationService(
        embedding_provider=DeterministicEmbeddingProvider(),
        query_rewriter=query_rewriter or ScriptedQueryRewriter(retrieval_query),
        answer_generator=answer_generator or SourceGroundedAnswerGenerator(answer),
        chat_model="deterministic-eval-chat",
        top_k=3,
        min_similarity=0.7,
        source_enricher=source_enricher or NoOpSourceEnricher(),
    )


def generate_eval_result(
    *,
    service: RAGOrchestrationService,
    db: Session,
    session_id: UUID,
    current_message: str,
    current_message_id: UUID | None = None,
) -> RAGOrchestrationResult:
    return asyncio.run(
        collect_final_result(
            service.generate_stream(
                db=db,
                session_id=session_id,
                current_message=current_message,
                current_message_id=current_message_id,
            )
        )
    )


async def collect_final_result(
    events: AsyncIterator[RAGOrchestrationStreamDelta | RAGOrchestrationStreamFinal],
) -> RAGOrchestrationResult:
    final: RAGOrchestrationStreamFinal | None = None
    async for event in events:
        if isinstance(event, RAGOrchestrationStreamFinal):
            final = event
    if final is None:
        raise AssertionError("stream completed without a final event")
    return final.result


def seed_eval_fixture(db: Session) -> SeededFixture:
    now = datetime.now(UTC)
    app_user = AppUser(
        id=uuid4(),
        clerk_user_id=f"user_{uuid4().hex}",
        email="eval@example.com",
        first_name="Eval",
        last_name="Runner",
        created_at=now,
        updated_at=now,
    )
    session = ChatSession(
        id=uuid4(),
        app_user_id=app_user.id,
        title="Escalation runbook",
        title_status="fallback",
        created_at=now,
        updated_at=now,
    )
    active_document, active_chunk = make_document_chunk(
        app_user_id=app_user.id,
        filename="Escalation Runbook.md",
        text="Escalation deadline is two business days after incident detection.",
        embedding=_unit_vector(0),
        now=now,
    )
    deleted_document, deleted_chunk = make_document_chunk(
        app_user_id=app_user.id,
        filename="Deleted Escalation Runbook.md",
        text="Deleted escalation source says one hour, but it must not be retrieved.",
        embedding=_unit_vector(0),
        now=now,
        deleted_at=now,
    )
    db.add_all([app_user, session, active_document, active_chunk, deleted_document, deleted_chunk])
    db.flush()
    db.add_all(
        [
            ChatMessage(
                id=uuid4(),
                session_id=session.id,
                role="user",
                content="Open the escalation runbook.",
                status="completed",
                created_at=now + timedelta(minutes=1),
            ),
            ChatMessage(
                id=uuid4(),
                session_id=session.id,
                role="assistant",
                content="It covers incident deadlines.",
                status="completed",
                created_at=now + timedelta(minutes=2),
            ),
            DocumentEmbedding(
                id=uuid4(),
                chunk_id=active_chunk.id,
                embedding_model="deterministic-eval-embedding",
                embedding=_unit_vector(0),
                created_at=now,
            ),
            DocumentEmbedding(
                id=uuid4(),
                chunk_id=deleted_chunk.id,
                embedding_model="deterministic-eval-embedding",
                embedding=_unit_vector(0),
                created_at=now,
            ),
        ]
    )
    db.commit()
    return SeededFixture(
        app_user=app_user,
        session=session,
        active_document=active_document,
        active_chunk=active_chunk,
        deleted_document=deleted_document,
        deleted_chunk=deleted_chunk,
    )


def make_document_chunk(
    *,
    app_user_id: UUID,
    filename: str,
    text: str,
    embedding: list[float],
    now: datetime,
    deleted_at: datetime | None = None,
) -> tuple[Document, DocumentChunk]:
    extension = ".md"
    document = Document(
        id=uuid4(),
        original_filename=filename,
        display_name=filename,
        media_type="text/markdown",
        file_extension=extension,
        byte_size=len(text.encode("utf-8")),
        sha256=sha256(text.encode("utf-8")).hexdigest(),
        object_bucket="eval-bucket",
        object_key=f"documents/originals/{uuid4().hex}{extension}",
        status="completed",
        uploaded_by_app_user_id=app_user_id,
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
        section_title="Escalation",
        chunk_metadata={},
        created_at=now,
    )
    if len(embedding) != 1536:
        raise ValueError("eval fixture embeddings must be 1536-dimensional")
    return document, chunk


def seed_component_outline_document(
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
        byte_size=16_000,
        sha256=sha256(b"daisyui-component-outline").hexdigest(),
        object_bucket="eval-bucket",
        object_key=f"documents/originals/{uuid4().hex}.txt",
        status="completed",
        uploaded_by_app_user_id=app_user_id,
        created_at=now,
        updated_at=now,
    )
    chunk_texts = _component_outline_chunk_texts()
    chunks = [
        DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            chunk_index=index,
            text=text,
            token_count=len(text.split()),
            page_number=None,
            section_title="daisyUI 5 components",
            chunk_metadata={},
            created_at=now + timedelta(seconds=index),
        )
        for index, text in enumerate(chunk_texts)
    ]
    color_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        chunk_index=len(chunks),
        text="### daisyUI color names\nColors are theme tokens, not components.",
        token_count=8,
        page_number=None,
        section_title="daisyUI 5 colors",
        chunk_metadata={},
        created_at=now + timedelta(seconds=len(chunks)),
    )
    db.add_all([document, *chunks, color_chunk])
    db.flush()
    db.add_all(
        [
            DocumentEmbedding(
                id=uuid4(),
                chunk_id=chunk.id,
                embedding_model="deterministic-eval-embedding",
                embedding=_unit_vector(2),
                created_at=now,
            )
            for chunk in chunks
        ]
    )
    db.add(
        DocumentEmbedding(
            id=uuid4(),
            chunk_id=color_chunk.id,
            embedding_model="deterministic-eval-embedding",
            embedding=_unit_vector(1),
            created_at=now,
        )
    )
    db.commit()
    return document, chunks


def _component_outline_chunk_texts() -> list[str]:
    component_names = [
        "accordion",
        "alert",
        "avatar",
        "badge",
        "breadcrumbs",
        "button",
        "calendar",
        "card",
        "carousel",
        "chat",
        "checkbox",
        "collapse",
        "countdown",
        "diff",
        "divider",
        "dock",
        "drawer",
        "dropdown",
        "fab",
        "fieldset",
        "file-input",
        "filter",
        "footer",
        "hero",
        "hover-3d",
        "hover-gallery",
        "indicator",
        "input",
        "join",
        "kbd",
        "label",
        "link",
        "list",
        "loading",
        "mask",
        "menu",
        "mockup-browser",
        "mockup-code",
        "mockup-phone",
        "mockup-window",
        "modal",
        "navbar",
        "pagination",
        "progress",
        "radial-progress",
        "radio",
        "range",
        "rating",
        "select",
        "skeleton",
        "stack",
        "stat",
        "status",
        "steps",
        "swap",
        "tab",
        "table",
        "text-rotate",
        "textarea",
        "theme-controller",
        "timeline",
        "toast",
        "toggle",
        "tooltip",
        "validator",
    ]
    chunks: list[str] = []
    for start in range(0, len(component_names), 22):
        chunks.append(
            "\n\n".join(
                [
                    f"### {name}\n[{name} docs](https://daisyui.com/components/{name}/)"
                    for name in component_names[start : start + 22]
                ]
            )
        )
    return chunks


def assert_test_database_url(test_database_url: str, app_database_url: str) -> None:
    test_url = make_url(test_database_url)
    app_url = make_url(app_database_url)
    if not _same_database(test_url, app_url):
        return

    raise ValueError(
        "TEST_DATABASE_URL must point at a database separate from DATABASE_URL because evals "
        "wipe app tables."
    )


def truncate_database(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
                    message_sources,
                    chat_messages,
                    chat_sessions,
                    document_embeddings,
                    ingestion_jobs,
                    document_chunks,
                    documents,
                    app_users
                """
            )
        )


def _same_database(first: URL, second: URL) -> bool:
    return (
        first.drivername == second.drivername
        and first.host == second.host
        and first.port == second.port
        and first.username == second.username
        and first.database == second.database
    )


def _unit_vector(index: int) -> list[float]:
    embedding = [0.0] * 1536
    embedding[index] = 1.0
    return embedding


if __name__ == "__main__":
    raise SystemExit(main())
