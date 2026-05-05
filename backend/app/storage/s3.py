from __future__ import annotations

from hashlib import sha256

import boto3
from botocore.client import Config

from app.core.config import Settings, get_settings
from app.storage.service import StoredObject


class S3ObjectStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = boto3.client(
            "s3",
            endpoint_url=self._settings.object_storage_endpoint,
            region_name=self._settings.object_storage_region,
            aws_access_key_id=self._settings.object_storage_access_key,
            aws_secret_access_key=self._settings.object_storage_secret_key,
            use_ssl=self._settings.object_storage_secure,
            config=Config(
                s3={
                    "addressing_style": (
                        "path" if self._settings.object_storage_force_path_style else "auto"
                    )
                }
            ),
        )

    def put_original(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        self._client.put_object(
            Bucket=self._settings.object_storage_bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return StoredObject(
            bucket=self._settings.object_storage_bucket,
            key=key,
            byte_size=len(content),
            sha256=sha256(content).hexdigest(),
        )

    def delete_original(self, *, key: str) -> None:
        self._client.delete_object(Bucket=self._settings.object_storage_bucket, Key=key)

    def get_original(self, *, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._settings.object_storage_bucket, Key=key)
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()
