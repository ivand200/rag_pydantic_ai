from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rag import Document, DocumentChunk
from app.retrieval.service import RetrievalResult

_AGGREGATE_TERMS = (
    "how many",
    "how much",
    "count",
    "number of",
    "list all",
    "all",
)
_HEADING_RE = re.compile(r"(?m)^###\s+([^\n#][^\n]*)\s*$")
_SUBJECT_PATTERNS = (
    re.compile(
        r"\bhow (?:many|much)\s+([a-z0-9][a-z0-9 -]*?)\s+"
        r"(?:does|do|are|is|has|have|in|from|for|$)"
    ),
    re.compile(
        r"\bnumber of\s+([a-z0-9][a-z0-9 -]*?)\s+"
        r"(?:does|do|are|is|has|have|in|from|for|$)"
    ),
    re.compile(r"\bcount(?: of)?\s+([a-z0-9][a-z0-9 -]*?)\s+(?:in|from|for|$)"),
    re.compile(r"\blist(?: all)?\s+([a-z0-9][a-z0-9 -]*?)\s+(?:in|from|for|$)"),
)
_STOP_WORDS = {"a", "an", "all", "of", "the", "this", "these", "those"}


class SourceEnricher(Protocol):
    def enrich(
        self,
        *,
        db: Session,
        current_message: str,
        retrieval_query: str,
        sources: Sequence[RetrievalResult],
    ) -> list[RetrievalResult]: ...


@dataclass(frozen=True)
class NoOpSourceEnricher:
    def enrich(
        self,
        *,
        db: Session,
        current_message: str,
        retrieval_query: str,
        sources: Sequence[RetrievalResult],
    ) -> list[RetrievalResult]:
        return list(sources)


@dataclass(frozen=True)
class MarkdownSectionOutlineEnricher:
    max_documents: int = 3
    min_items: int = 2
    max_items: int = 200

    def enrich(
        self,
        *,
        db: Session,
        current_message: str,
        retrieval_query: str,
        sources: Sequence[RetrievalResult],
    ) -> list[RetrievalResult]:
        if not sources:
            return []

        subjects = _aggregate_subjects(f"{current_message} {retrieval_query}")
        if not subjects:
            return list(sources)

        document_ids = _ordered_document_ids(sources)[: self.max_documents]
        chunks_by_document = _load_chunks_by_document(db=db, document_ids=document_ids)
        scores_by_document = {
            document_id: max(
                source.score for source in sources if source.document_id == document_id
            )
            for document_id in document_ids
        }
        outline_sources: list[RetrievalResult] = []
        for document_id in document_ids:
            document_chunks = chunks_by_document.get(document_id, [])
            outline = _outline_for_matching_sections(
                document_chunks=document_chunks,
                subjects=subjects,
                min_items=self.min_items,
                max_items=self.max_items,
            )
            if outline is None:
                continue

            first_chunk, document_name, section_title, item_names = outline
            outline_sources.append(
                RetrievalResult(
                    document_id=document_id,
                    document_name=document_name,
                    chunk_id=first_chunk.id,
                    chunk_index=first_chunk.chunk_index,
                    text="\n".join(
                        [
                            f"Derived outline from {document_name}.",
                            f"Matching section: {section_title}",
                            f"Item count: {len(item_names)}",
                            "Items:",
                            ", ".join(item_names),
                        ]
                    ),
                    score=scores_by_document[document_id],
                    page_number=first_chunk.page_number,
                    section_title="Derived document outline",
                )
            )

        return [*outline_sources, *sources]


def _ordered_document_ids(sources: Sequence[RetrievalResult]) -> list[UUID]:
    return list(dict.fromkeys(source.document_id for source in sources))


def _load_chunks_by_document(
    *,
    db: Session,
    document_ids: Sequence[UUID],
) -> dict[UUID, list[tuple[DocumentChunk, str]]]:
    rows = db.execute(
        select(DocumentChunk, Document.display_name)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.document_id.in_(document_ids),
            Document.status == "completed",
            Document.deleted_at.is_(None),
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
    ).all()
    chunks_by_document: dict[UUID, list[tuple[DocumentChunk, str]]] = {}
    for chunk, document_name in rows:
        chunks_by_document.setdefault(chunk.document_id, []).append((chunk, document_name))
    return chunks_by_document


def _outline_for_matching_sections(
    *,
    document_chunks: Sequence[tuple[DocumentChunk, str]],
    subjects: set[str],
    min_items: int,
    max_items: int,
) -> tuple[DocumentChunk, str, str, list[str]] | None:
    names: list[str] = []
    seen: set[str] = set()
    first_chunk: DocumentChunk | None = None
    first_document_name: str | None = None
    first_section_title: str | None = None

    for chunk, document_name in document_chunks:
        section_title = chunk.section_title or ""
        if not _matches_any_subject(section_title, subjects):
            continue

        for name in _heading_names(chunk.text):
            normalized_name = " ".join(name.split())
            key = normalized_name.lower()
            if not normalized_name or key in seen:
                continue

            if first_chunk is None:
                first_chunk = chunk
                first_document_name = document_name
                first_section_title = section_title

            seen.add(key)
            names.append(normalized_name)
            if len(names) >= max_items:
                break

    if first_chunk is None or first_document_name is None or len(names) < min_items:
        return None

    return first_chunk, first_document_name, first_section_title or "matching section", names


def _aggregate_subjects(text: str) -> set[str]:
    normalized = text.lower()
    if not any(term in normalized for term in _AGGREGATE_TERMS):
        return set()

    subjects: set[str] = set()
    for pattern in _SUBJECT_PATTERNS:
        for match in pattern.finditer(normalized):
            words = [word for word in _words(match.group(1)) if word not in _STOP_WORDS]
            if words:
                subjects.add(_singular(words[-1]))
    return subjects


def _heading_names(text: str) -> list[str]:
    return [match.group(1) for match in _HEADING_RE.finditer(text)]


def _matches_any_subject(text: str, subjects: set[str]) -> bool:
    section_words = {_singular(word) for word in _words(text)}
    return bool(section_words & subjects)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return f"{word[:-3]}y"
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word
