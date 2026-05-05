from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    byte_size: int
    sha256: str


class ObjectStorage(Protocol):
    def put_original(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        """Store original uploaded bytes under a caller-generated safe key."""

    def delete_original(self, *, key: str) -> None:
        """Best-effort removal for objects that should not remain referenced."""

    def get_original(self, *, key: str) -> bytes:
        """Read original uploaded bytes by the app-owned object key."""
