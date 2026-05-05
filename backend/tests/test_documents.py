from collections.abc import Callable
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import Settings, get_settings
from app.main import create_app
from app.storage.dependencies import get_object_storage
from app.storage.fake import FakeObjectStorage
from app.storage.service import StoredObject


@pytest.fixture
def fake_storage(client: TestClient) -> FakeObjectStorage:
    storage = FakeObjectStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    return storage


@pytest.fixture
def auth_headers(make_clerk_token: Callable[..., str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_clerk_token()}"}


def test_upload_creates_queued_document_and_ingestion_job_after_object_storage_succeeds(
    client: TestClient,
    fake_storage: FakeObjectStorage,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    response = client.post(
        "/api/documents",
        headers=auth_headers,
        files={"file": ("../unsafe-name.txt", b"hello document", "text/plain")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body | {"id": body["id"], "uploaded_by": body["uploaded_by"]} == {
        "id": body["id"],
        "filename": "unsafe-name.txt",
        "media_type": "text/plain",
        "byte_size": 14,
        "status": "queued",
        "uploaded_by": body["uploaded_by"],
        "uploaded_at": body["uploaded_at"],
        "deleted": False,
        "deleted_at": None,
        "failure_reason": None,
    }
    assert UUID(body["id"])

    with migrated_database.connect() as connection:
        stored = connection.execute(
            text(
                """
                SELECT documents.object_key, ingestion_jobs.status
                FROM documents
                JOIN ingestion_jobs ON ingestion_jobs.document_id = documents.id
                WHERE documents.id = :document_id
                """
            ),
            {"document_id": body["id"]},
        ).one()

    assert stored.status == "queued"
    assert stored.object_key in fake_storage.objects
    assert "../unsafe-name.txt" not in stored.object_key


def test_upload_storage_failure_does_not_create_document_or_ingestion_job(
    client: TestClient,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    client.app.dependency_overrides[get_object_storage] = lambda: FailingObjectStorage()

    with TestClient(client.app, raise_server_exceptions=False) as no_raise_client:
        response = no_raise_client.post(
            "/api/documents",
            headers=auth_headers,
            files={"file": ("notes.txt", b"hello document", "text/plain")},
        )

    assert response.status_code == 500
    assert table_count(migrated_database, "documents") == 0
    assert table_count(migrated_database, "ingestion_jobs") == 0


def test_upload_rejects_more_than_one_file(
    client: TestClient,
    fake_storage: FakeObjectStorage,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    response = client.post(
        "/api/documents",
        headers=auth_headers,
        files=[
            ("file", ("first.txt", b"one", "text/plain")),
            ("file", ("second.txt", b"two", "text/plain")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "multiple_files"
    assert not fake_storage.objects
    assert table_count(migrated_database, "documents") == 0


def test_upload_rejects_unsupported_extensions(
    client: TestClient,
    fake_storage: FakeObjectStorage,
    auth_headers: dict[str, str],
    migrated_database: Engine,
) -> None:
    response = client.post(
        "/api/documents",
        headers=auth_headers,
        files={"file": ("malware.exe", b"nope", "application/octet-stream")},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"
    assert not fake_storage.objects
    assert table_count(migrated_database, "documents") == 0


def test_upload_rejects_files_larger_than_configured_limit(
    test_key_pair: dict[str, str],
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    storage = FakeObjectStorage()
    app = create_app()
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: Settings(
        clerk_jwt_public_key=test_key_pair["public"],
        max_upload_bytes=4,
    )

    with TestClient(app) as small_upload_client:
        response = small_upload_client.post(
            "/api/documents",
            headers={"Authorization": f"Bearer {make_clerk_token()}"},
            files={"file": ("notes.md", b"12345", "text/markdown")},
        )

    get_settings.cache_clear()

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "upload_too_large"
    assert not storage.objects
    assert table_count(migrated_database, "documents") == 0


def test_list_returns_active_shared_documents_only(
    client: TestClient,
    fake_storage: FakeObjectStorage,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    first_headers = {"Authorization": f"Bearer {make_clerk_token(sub='user_first')}"}
    second_headers = {
        "Authorization": f"Bearer {make_clerk_token(sub='user_second', email='second@example.com')}"
    }
    first_upload = upload_text_document(client, first_headers, "first.txt")
    second_upload = upload_text_document(client, second_headers, "second.md")
    client.delete(f"/api/documents/{first_upload['id']}", headers=second_headers)

    response = client.get("/api/documents", headers=first_headers)

    assert response.status_code == 200
    assert [document["id"] for document in response.json()] == [second_upload["id"]]
    assert table_count(migrated_database, "documents") == 2


def test_any_authenticated_user_can_tombstone_document_idempotently(
    client: TestClient,
    fake_storage: FakeObjectStorage,
    make_clerk_token: Callable[..., str],
    migrated_database: Engine,
) -> None:
    uploader_headers = {"Authorization": f"Bearer {make_clerk_token(sub='uploader')}"}
    deleter_headers = {
        "Authorization": f"Bearer {make_clerk_token(sub='deleter', email='deleter@example.com')}"
    }
    uploaded = upload_text_document(client, uploader_headers, "shared.txt")

    first_delete = client.delete(f"/api/documents/{uploaded['id']}", headers=deleter_headers)
    second_delete = client.delete(f"/api/documents/{uploaded['id']}", headers=deleter_headers)

    assert first_delete.status_code == 200
    assert second_delete.status_code == 200
    assert second_delete.json()["deleted"] is True

    with migrated_database.connect() as connection:
        deleted = connection.execute(
            text(
                """
                SELECT
                    documents.deleted_at,
                    documents.deleted_by_app_user_id,
                    deleted_by.id AS expected_deleted_by_app_user_id
                FROM documents
                JOIN app_users deleted_by ON deleted_by.clerk_user_id = 'deleter'
                WHERE documents.id = :document_id
                """
            ),
            {"document_id": uploaded["id"]},
        ).one()

    assert deleted.deleted_at is not None
    assert deleted.deleted_by_app_user_id == deleted.expected_deleted_by_app_user_id


def test_fake_storage_records_and_deletes_original_objects() -> None:
    storage = FakeObjectStorage(bucket="documents")

    stored = storage.put_original(
        key="documents/originals/generated.txt",
        content=b"hello",
        content_type="text/plain",
    )
    storage.delete_original(key=stored.key)

    assert stored.bucket == "documents"
    assert stored.byte_size == 5
    assert stored.key not in storage.objects


def upload_text_document(
    client: TestClient,
    headers: dict[str, str],
    filename: str,
) -> dict[str, object]:
    response = client.post(
        "/api/documents",
        headers=headers,
        files={"file": (filename, b"content", "text/plain")},
    )
    assert response.status_code == 201
    return response.json()


def table_count(engine: Engine, table_name: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()


class FailingObjectStorage:
    def put_original(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        raise RuntimeError("storage unavailable")

    def delete_original(self, *, key: str) -> None:
        return None
