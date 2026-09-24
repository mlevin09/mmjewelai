"""Private create-only object-storage port."""

from typing import Protocol

from .models import AssetContentType, ContentHash, ObjectKey, StoredObject


class AssetStorageError(RuntimeError):
    """Safe base error for object-storage failures."""


class AssetStorageConflictError(AssetStorageError):
    pass


class PrivateObjectStore(Protocol):
    def put_if_absent(
        self,
        object_key: ObjectKey,
        content: bytes,
        *,
        content_type: AssetContentType,
        content_hash: ContentHash,
    ) -> StoredObject: ...
