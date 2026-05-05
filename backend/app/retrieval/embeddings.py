from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from openai import OpenAI

from app.core.config import Settings

EMBEDDING_DIMENSIONS = 1536


class EmbeddingProvider(Protocol):
    model: str

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingConfigurationError(RuntimeError):
    pass


class OpenAIEmbeddingProvider:
    def __init__(self, *, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise EmbeddingConfigurationError("OPENAI_API_KEY is required for OpenAI embeddings.")

        self.model = settings.embedding_model
        self._client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        response = self._client.embeddings.create(
            model=self.model,
            input=list(texts),
            encoding_format="float",
        )
        embeddings = [item.embedding for item in response.data]
        _validate_embeddings(embeddings)
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


def _validate_embeddings(embeddings: Sequence[Sequence[float]]) -> None:
    for embedding in embeddings:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding provider returned {len(embedding)} dimensions; "
                f"expected {EMBEDDING_DIMENSIONS}."
            )
