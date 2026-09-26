"""Google Cloud Storage implementations of private Asset storage and signing ports."""

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.auth.credentials import Credentials, Signing
from google.auth.transport.requests import Request
from google.cloud import storage
from jewelai_assets import (
    AssetAccessUnavailableError,
    AssetContentType,
    AssetStorageConflictError,
    AssetStorageError,
    PrivateObjectMetadata,
    StoredObject,
)
from jewelai_assets.models import ContentHash, ObjectKey, ObjectVersionToken
from pydantic import TypeAdapter, ValidationError

from .config import GcsAssetStorageConfig, validate_signing_service_account_email

JEWELAI_SHA256_METADATA_KEY = "jewelai-sha256"
_OBJECT_KEY = TypeAdapter(ObjectKey)
_CONTENT_HASH = TypeAdapter(ContentHash)
_VERSION_TOKEN = TypeAdapter(ObjectVersionToken)


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

    def inspect(self, object_key: ObjectKey) -> PrivateObjectMetadata | None:
        """Read metadata for one exact key without downloading object content."""
        try:
            object_key = _OBJECT_KEY.validate_python(object_key)
        except ValidationError as exc:
            raise AssetStorageError("Asset storage input is invalid") from exc
        try:
            blob = self._bucket.get_blob(object_key)
        except NotFound:
            return None
        except Exception as exc:
            raise AssetStorageError("Google Cloud Storage metadata inspection failed") from exc
        if blob is None:
            return None
        try:
            if blob.generation is None:
                raise ValueError("object generation is unavailable")
            metadata = blob.metadata or {}
            inspected = PrivateObjectMetadata(
                object_key=blob.name,
                content_type=blob.content_type,
                content_hash=metadata.get(JEWELAI_SHA256_METADATA_KEY),
                byte_size=blob.size,
                created_at=blob.time_created,
                version_token=str(blob.generation),
            )
        except Exception as exc:
            raise AssetStorageConflictError(
                "Private object metadata is incomplete or invalid"
            ) from exc
        if inspected.object_key != object_key:
            raise AssetStorageConflictError("Private object metadata key does not match request")
        return inspected

    def delete_if_version(self, object_key: ObjectKey, version_token: ObjectVersionToken) -> bool:
        """Delete one exact GCS generation; never delete a replacement object."""
        try:
            object_key = _OBJECT_KEY.validate_python(object_key)
            version_token = _VERSION_TOKEN.validate_python(version_token)
            generation = int(version_token)
            if generation <= 0 or str(generation) != version_token:
                raise ValueError("GCS generation must be a canonical positive integer")
        except (ValidationError, ValueError) as exc:
            raise AssetStorageError("Asset storage input is invalid") from exc
        try:
            self._bucket.blob(object_key).delete(if_generation_match=generation)
        except NotFound:
            return False
        except PreconditionFailed as exc:
            raise AssetStorageConflictError(
                "Private object changed after maintenance inspection"
            ) from exc
        except Exception as exc:
            raise AssetStorageError("Google Cloud Storage conditional delete failed") from exc
        return True


class GcsPrivateObjectAccessSigner:
    def __init__(
        self,
        config: GcsAssetStorageConfig,
        *,
        client: Any | None = None,
        credentials: Credentials | None = None,
        auth_request: Any | None = None,
    ):
        self.config = config
        try:
            self._client = (
                client
                if client is not None
                else storage.Client(project=config.project_id, credentials=credentials)
            )
            self._bucket = self._client.bucket(config.bucket_name)
            self._credentials = (
                credentials if credentials is not None else _client_credentials(self._client)
            )
            self._auth_request = auth_request
        except Exception as exc:
            raise AssetAccessUnavailableError("Google Cloud asset signing is unavailable") from exc

    def sign_read(self, object_key: ObjectKey, expires_at: datetime) -> str:
        try:
            object_key = _OBJECT_KEY.validate_python(object_key)
            if expires_at.tzinfo is None or expires_at.utcoffset() is None:
                raise ValueError("expiration must be timezone-aware")
            signing_arguments = self._signing_arguments()
            url = self._bucket.blob(object_key).generate_signed_url(
                version="v4",
                expiration=expires_at,
                method="GET",
                scheme="https",
                **signing_arguments,
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

    def _signing_arguments(self) -> dict[str, Any]:
        credentials = self._credentials
        if isinstance(credentials, Signing):
            return {"credentials": credentials}

        credentials.refresh(self._auth_request if self._auth_request is not None else Request())
        access_token = credentials.token
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("refreshed credentials did not provide an access token")

        service_account_email = self.config.signing_service_account_email or getattr(
            credentials, "service_account_email", None
        )
        if not isinstance(service_account_email, str):
            raise ValueError("signing service-account email is unavailable")
        validate_signing_service_account_email(service_account_email)
        return {
            "credentials": credentials,
            "service_account_email": service_account_email,
            "access_token": access_token,
        }


def _client_credentials(client: Any) -> Credentials:
    # google-cloud-storage 3.x has no public credentials accessor. Blob's own
    # signing implementation uses the same client attribute when credentials
    # are not supplied explicitly, so keep this compatibility access isolated.
    credentials = getattr(client, "_credentials", None)
    if not isinstance(credentials, Credentials):
        raise ValueError("Google Cloud client credentials are unavailable")
    return credentials
