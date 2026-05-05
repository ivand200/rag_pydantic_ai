from functools import lru_cache

from app.storage.s3 import S3ObjectStorage
from app.storage.service import ObjectStorage


@lru_cache
def get_object_storage() -> ObjectStorage:
    return S3ObjectStorage()
