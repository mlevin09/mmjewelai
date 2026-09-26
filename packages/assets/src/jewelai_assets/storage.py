"""Private create-only object-storage port."""

from typing import Protocol

from .models import (
    AssetContentType,
    ContentHash,
    ObjectKey,
    ObjectVersionToken,
    PrivateObjectMetadata,
    StoredObject,
)


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


class PrivateObjectMetadataReader(Protocol):
    """Metadata-read authority for exact canonical object keys only."""

    def inspect(self, object_key: ObjectKey) -> PrivateObjectMetadata | None: ...


class PrivateObjectVersionDeleter(Protocol):
    """Narrow delete authority requiring an exact previously inspected version."""

    def delete_if_version(
        self, object_key: ObjectKey, version_token: ObjectVersionToken
    ) -> bool: ...


class PrivateObjectMaintenance(PrivateObjectMetadataReader, PrivateObjectVersionDeleter, Protocol):
    """Combined operator capability; normal generation depends only on PrivateObjectStore."""
