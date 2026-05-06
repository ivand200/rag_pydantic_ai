from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "rag-service-backend"
    clerk_jwt_public_key: str | None = None
    backend_cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://rag_service:rag_service@localhost:5432/rag_service"
    test_database_url: str | None = (
        "postgresql+psycopg://rag_service:rag_service@localhost:5432/rag_service_test"
    )
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-5.4-mini"
    embedding_model: str = "text-embedding-3-small"
    rag_chunk_target_tokens: int = Field(default=512, gt=0)
    rag_chunk_overlap_tokens: int = Field(default=80, ge=0)
    rag_query_rewrite_history_messages: int = Field(default=6, ge=0, le=50)
    rag_answer_history_messages: int = Field(default=6, ge=0, le=50)
    rag_retrieval_top_k: int = Field(default=5, gt=0, le=100)
    rag_retrieval_min_similarity: float = Field(default=0.45, ge=0, le=1)
    max_upload_bytes: int = Field(default=10_485_760, gt=0)
    max_extracted_chars: int = Field(default=500_000, gt=0)
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_bucket: str = "rag-documents"
    object_storage_access_key: str | None = None
    object_storage_secret_key: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_secure: bool = False
    object_storage_force_path_style: bool = True
    ingestion_worker_id: str = "local-worker-1"
    ingestion_max_attempts: int = Field(default=3, ge=1, le=20)
    ingestion_base_retry_seconds: int = Field(default=30, ge=1, le=86_400)
    ingestion_stale_after_seconds: int = Field(default=1_800, ge=1, le=86_400)
    ingestion_stale_recovery_batch_size: int = Field(default=10, ge=1, le=1_000)

    @property
    def backend_cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_rag_settings(self) -> "Settings":
        if self.rag_chunk_overlap_tokens >= self.rag_chunk_target_tokens:
            raise ValueError("RAG_CHUNK_OVERLAP_TOKENS must be less than RAG_CHUNK_TARGET_TOKENS")

        if self.rag_chunk_overlap_tokens > self.rag_chunk_target_tokens / 2:
            raise ValueError(
                "RAG_CHUNK_OVERLAP_TOKENS must not be more than half RAG_CHUNK_TARGET_TOKENS"
            )

        return self

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
