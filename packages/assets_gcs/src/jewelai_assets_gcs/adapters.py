"""Google Cloud Storage implementations of private Asset storage and signing ports."""

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from jewelai_assets import (
    AssetAccessUnavailableError,
    AssetContentType,
    AssetStorageConflictError,
    AssetStorageError,
    StoredObject,
)
from jewelai_assets.models import ContentHash, ObjectKey
from pydantic import TypeAdapter, ValidationError

from .config import GcsAssetStorageConfig

JEWELAI_SHA256_METADATA_KEY = "jewelai-sha256"
_OBJECT_KEY = TypeAdapter(ObjectKey)
_CONTENT_HASH = TypeAdapter(ContentHash)


class GcsPrivateObjectStore:
    def __init__(self, config: GcsAssetStorageConfig, *, client: Any | None = None):
        self.config = config
        try:
            self._client = (
                client if client is not None else storage.Client(project=config.project_id)
            )
            self._bucket = self._client.bucket(config.bucket_name)
        except Exception as exc:
            raise AssetStorageError("Google Cloud Storage is unavailable") from exc

    def put_if_absent(
        self,
        object_key: ObjectKey,
        content: bytes,
        *,
        content_type: AssetContentType,
        content_hash: ContentHash,
    ) -> StoredObject:
        try:
            object_key = _OBJECT_KEY.validate_python(object_key)
            content_hash = _CONTENT_HASH.validate_python(content_hash)
            content_type = AssetContentType(content_type)
        except (ValidationError, ValueError) as exc:
            raise AssetStorageError("Asset storage input is invalid") from exc

        blob = self._bucket.blob(object_key)
        blob.metadata = {JEWELAI_SHA256_METADATA_KEY: content_hash}
        try:
            blob.upload_from_string(
                content,
                content_type=content_type.value,
                if_generation_match=0,
            )
        except PreconditionFailed:
            return self._verify_existing(object_key, content_type, content_hash, len(content))
        except Exception as exc:
            raise AssetStorageError("Google Cloud Storage create-only write failed") from exc
        return StoredObject(
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=len(content),
        )

    def _verify_existing(
        self,
        object_key: ObjectKey,
        content_type: AssetContentType,
        content_hash: ContentHash,
        byte_size: int,
    ) -> StoredObject:
        try:
            existing = self._bucket.get_blob(object_key)
        except Exception as exc:
            raise AssetStorageError("Google Cloud Storage metadata verification failed") from exc
        metadata = existing.metadata or {} if existing is not None else {}
        matches = existing is not None and (
            existing.name,
            existing.content_type,
            existing.size,
            metadata.get(JEWELAI_SHA256_METADATA_KEY),
        ) == (object_key, content_type.value, byte_size, content_hash)
        if not matches:
            raise AssetStorageConflictError(
                "Existing private object metadata conflicts with Asset content"
            )
        return StoredObject(
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=byte_size,
        )


class GcsPrivateObjectAccessSigner:
    def __init__(self, config: GcsAssetStorageConfig, *, client: Any | None = None):
        self.config = config
        try:
            self._client = (
                client if client is not None else storage.Client(project=config.project_id)
            )
            self._bucket = self._client.bucket(config.bucket_name)
        except Exception as exc:
            raise AssetAccessUnavailableError("Google Cloud asset signing is unavailable") from exc

    def sign_read(self, object_key: ObjectKey, expires_at: datetime) -> str:
        try:
            object_key = _OBJECT_KEY.validate_python(object_key)
            if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                raise ValueError("expiration must be timezone-aware")
            url = self._bucket.blob(object_key).generate_signed_url(
                version="v4",
                expiration=expires_at,
                method="GET",
                scheme="https",
            )
        except Exception as exc:
            raise AssetAccessUnavailableError("Google Cloud asset signing is unavailable") from exc
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (
            parsed is None
            or parsed.scheme != "https"
            or not parsed.netloc
            or any(character.isspace() for character in url)
        ):
            raise AssetAccessUnavailableError("Google Cloud asset signer returned an invalid URL")
        return url
