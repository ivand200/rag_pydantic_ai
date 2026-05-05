from __future__ import annotations

from hashlib import sha256

from app.storage.service import StoredObject


class FakeObjectStorage:
    def __init__(self, bucket: str = "test-documents") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    def put_original(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        self.objects[key] = content
        self.content_types[key] = content_type
        return StoredObject(
            bucket=self.bucket,
            key=key,
            byte_size=len(content),
            sha256=sha256(content).hexdigest(),
        )

    def delete_original(self, *, key: str) -> None:
        self.objects.pop(key, None)
        self.content_types.pop(key, None)

    def get_original(self, *, key: str) -> bytes:
        return self.objects[key]
