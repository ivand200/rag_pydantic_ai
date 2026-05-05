from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rag import Document, DocumentChunk, DocumentEmbedding
from app.retrieval.embeddings import EmbeddingProvider


@dataclass(frozen=True)
class RetrievalResult:
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_index: int
    text: str
    score: float
    page_number: int | None
    section_title: str | None


def retrieve_relevant_chunks(
    *,
    db: Session,
    embedding_provider: EmbeddingProvider,
    query: str,
    top_k: int,
    min_similarity: float,
) -> list[RetrievalResult]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if min_similarity < 0 or min_similarity > 1:
        raise ValueError("min_similarity must be between 0 and 1")

    query_embedding = embedding_provider.embed_query(query)
    cosine_distance = DocumentEmbedding.embedding.cosine_distance(query_embedding)
    similarity = 1 - cosine_distance

    rows = db.execute(
        select(DocumentChunk, Document.display_name, similarity.label("similarity"))
        .join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.status == "completed",
            Document.deleted_at.is_(None),
            similarity >= min_similarity,
        )
        .order_by(cosine_distance.asc(), DocumentChunk.created_at.asc(), DocumentChunk.id.asc())
        .limit(top_k)
    ).all()

    return [
        RetrievalResult(
            document_id=chunk.document_id,
            document_name=document_name,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            score=float(score),
            page_number=chunk.page_number,
            section_title=chunk.section_title,
        )
        for chunk, document_name, score in rows
    ]
