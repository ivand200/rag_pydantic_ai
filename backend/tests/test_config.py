import pytest
from pydantic import ValidationError

from app.core.config import Settings

SETTINGS_ENV_KEYS = [
    "EMBEDDING_MODEL",
    "RAG_RETRIEVAL_TOP_K",
    "OBJECT_STORAGE_BUCKET",
    "OPENAI_API_KEY",
    "RAG_CHUNK_TARGET_TOKENS",
    "RAG_CHUNK_OVERLAP_TOKENS",
]


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_rag_runtime_settings_have_approved_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.rag_retrieval_top_k == 5
    assert settings.rag_retrieval_min_similarity == 0.45
    assert settings.object_storage_bucket == "rag-documents"
    assert settings.max_extracted_chars == 500_000


def test_openai_key_is_optional_for_foundation_runtime() -> None:
    settings = Settings(openai_api_key=None, _env_file=None)

    assert settings.openai_api_key is None


def test_rejects_chunk_overlap_equal_to_target() -> None:
    with pytest.raises(ValidationError, match="RAG_CHUNK_OVERLAP_TOKENS"):
        Settings(rag_chunk_target_tokens=512, rag_chunk_overlap_tokens=512, _env_file=None)


def test_rejects_chunk_overlap_more_than_half_target() -> None:
    with pytest.raises(ValidationError, match="RAG_CHUNK_OVERLAP_TOKENS"):
        Settings(rag_chunk_target_tokens=512, rag_chunk_overlap_tokens=257, _env_file=None)
