from sqlalchemy import text
from sqlalchemy.engine import Engine


def test_app_users_migration_creates_required_identity_constraints(
    migrated_database: Engine,
) -> None:
    with migrated_database.connect() as connection:
        columns = {
            row.column_name: row
            for row in connection.execute(
                text(
                    """
                    SELECT column_name, is_nullable, data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_name = 'app_users'
                    """
                )
            )
        }
        unique_constraints = {
            row.constraint_name
            for row in connection.execute(
                text(
                    """
                    SELECT tc.constraint_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.constraint_column_usage ccu
                      ON tc.constraint_name = ccu.constraint_name
                    WHERE tc.table_name = 'app_users'
                      AND tc.constraint_type = 'UNIQUE'
                      AND ccu.column_name = 'clerk_user_id'
                    """
                )
            )
        }

    assert columns["id"].udt_name == "uuid"
    assert columns["clerk_user_id"].is_nullable == "NO"
    assert "uq_app_users_clerk_user_id" in unique_constraints


def test_rag_migration_creates_document_storage_and_ingestion_contracts(
    migrated_database: Engine,
) -> None:
    with migrated_database.connect() as connection:
        extension_is_installed = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar_one()
        vector_columns = connection.execute(
            text(
                """
                SELECT format_type(attribute.atttypid, attribute.atttypmod) AS vector_type
                FROM pg_attribute attribute
                JOIN pg_class class ON class.oid = attribute.attrelid
                WHERE class.relname = 'document_embeddings'
                  AND attribute.attname = 'embedding'
                """
            )
        ).scalar_one()
        document_columns = _columns_for(connection, "documents")
        chunk_columns = _columns_for(connection, "document_chunks")
        embedding_columns = _columns_for(connection, "document_embeddings")
        ingestion_columns = _columns_for(connection, "ingestion_jobs")
        document_unique_constraints = _unique_constraints_for(connection, "documents")
        chunk_unique_constraints = _unique_constraints_for(connection, "document_chunks")
        embedding_unique_constraints = _unique_constraints_for(connection, "document_embeddings")
        document_foreign_keys = _foreign_keys_for(connection, "documents")
        chunk_foreign_keys = _foreign_keys_for(connection, "document_chunks")
        embedding_foreign_keys = _foreign_keys_for(connection, "document_embeddings")
        ingestion_foreign_keys = _foreign_keys_for(connection, "ingestion_jobs")
        document_checks = _check_constraints_for(connection, "documents")
        ingestion_checks = _check_constraints_for(connection, "ingestion_jobs")

    assert extension_is_installed
    assert vector_columns == "vector(1536)"
    assert set(document_columns) == {
        "id",
        "original_filename",
        "display_name",
        "media_type",
        "file_extension",
        "byte_size",
        "sha256",
        "object_bucket",
        "object_key",
        "status",
        "failure_reason",
        "uploaded_by_app_user_id",
        "deleted_by_app_user_id",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert set(chunk_columns) == {
        "id",
        "document_id",
        "chunk_index",
        "text",
        "token_count",
        "page_number",
        "section_title",
        "metadata",
        "created_at",
    }
    assert set(embedding_columns) == {
        "id",
        "chunk_id",
        "embedding_model",
        "embedding",
        "created_at",
    }
    assert set(ingestion_columns) == {
        "id",
        "document_id",
        "status",
        "attempt_count",
        "max_attempts",
        "next_run_at",
        "locked_at",
        "locked_by",
        "last_error",
        "created_at",
        "updated_at",
        "completed_at",
    }
    assert document_columns["deleted_at"].is_nullable == "YES"
    assert document_columns["uploaded_by_app_user_id"].is_nullable == "NO"
    assert ("uploaded_by_app_user_id", "app_users", "id") in document_foreign_keys
    assert ("deleted_by_app_user_id", "app_users", "id") in document_foreign_keys
    assert ("document_id", "documents", "id") in chunk_foreign_keys
    assert ("chunk_id", "document_chunks", "id") in embedding_foreign_keys
    assert ("document_id", "documents", "id") in ingestion_foreign_keys
    assert "uq_documents_object_key" in document_unique_constraints
    assert "uq_document_chunks_document_index" in chunk_unique_constraints
    assert "uq_document_embeddings_chunk_id" in embedding_unique_constraints
    assert "ck_documents_status" in document_checks
    assert "ck_ingestion_jobs_status" in ingestion_checks


def test_rag_migration_creates_chat_and_source_attribution_contracts(
    migrated_database: Engine,
) -> None:
    with migrated_database.connect() as connection:
        session_columns = _columns_for(connection, "chat_sessions")
        message_columns = _columns_for(connection, "chat_messages")
        source_columns = _columns_for(connection, "message_sources")
        session_foreign_keys = _foreign_keys_for(connection, "chat_sessions")
        message_foreign_keys = _foreign_keys_for(connection, "chat_messages")
        source_foreign_keys = _foreign_keys_for(connection, "message_sources")
        source_unique_constraints = _unique_constraints_for(connection, "message_sources")
        message_checks = _check_constraints_for(connection, "chat_messages")
        session_checks = _check_constraints_for(connection, "chat_sessions")

    assert set(session_columns) == {
        "id",
        "app_user_id",
        "title",
        "title_status",
        "created_at",
        "updated_at",
        "last_message_at",
    }
    assert set(message_columns) == {
        "id",
        "session_id",
        "role",
        "content",
        "status",
        "model",
        "retrieval_query",
        "usage",
        "created_at",
    }
    assert set(source_columns) == {
        "id",
        "message_id",
        "document_id",
        "document_name",
        "chunk_id",
        "rank",
        "score",
        "excerpt",
        "page_number",
        "section_title",
        "document_deleted_at",
    }
    assert ("app_user_id", "app_users", "id") in session_foreign_keys
    assert ("session_id", "chat_sessions", "id") in message_foreign_keys
    assert ("message_id", "chat_messages", "id") in source_foreign_keys
    assert ("document_id", "documents", "id") in source_foreign_keys
    assert ("chunk_id", "document_chunks", "id") in source_foreign_keys
    assert "uq_message_sources_message_rank" in source_unique_constraints
    assert {"ck_chat_messages_role", "ck_chat_messages_status"} <= message_checks
    assert "ck_chat_sessions_title_status" in session_checks


def _columns_for(connection, table_name: str) -> dict[str, object]:
    return {
        row.column_name: row
        for row in connection.execute(
            text(
                """
                SELECT column_name, is_nullable, data_type, udt_name
                FROM information_schema.columns
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
    }


def _unique_constraints_for(connection, table_name: str) -> set[str]:
    return {
        row.constraint_name
        for row in connection.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_name = :table_name
                  AND constraint_type = 'UNIQUE'
                """
            ),
            {"table_name": table_name},
        )
    }


def _check_constraints_for(connection, table_name: str) -> set[str]:
    return {
        row.constraint_name
        for row in connection.execute(
            text(
                """
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_name = :table_name
                  AND constraint_type = 'CHECK'
                """
            ),
            {"table_name": table_name},
        )
    }


def _foreign_keys_for(connection, table_name: str) -> set[tuple[str, str, str]]:
    return {
        (row.column_name, row.foreign_table_name, row.foreign_column_name)
        for row in connection.execute(
            text(
                """
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.table_name = :table_name
                  AND tc.constraint_type = 'FOREIGN KEY'
                """
            ),
            {"table_name": table_name},
        )
    }
