"""Bounded one-shot asset ingestion orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from .models import (
    ASSET_SCHEMA_VERSION,
    Asset,
    AssetContentType,
    AssetErrorCode,
    AssetIngestionPolicy,
    AssetIngestionRequest,
    AssetStatus,
    PrivateObjectMetadata,
    StoredObject,
)
from .storage import AssetStorageConflictError, AssetStorageError, PrivateObjectStore


class AssetIngestionError(RuntimeError):
    pass


class AssetContentRejectedError(AssetIngestionError):
    pass


class AssetConflictError(AssetIngestionError):
    pass


class AssetLineageError(AssetIngestionError):
    pass


class AssetMetadataRepository(Protocol):
    def find_asset(self, asset_id: UUID, organization_id: UUID) -> Asset | None: ...

    def create_pending_asset(self, asset: Asset) -> Asset: ...

    def mark_asset_ready(
        self, asset_id: UUID, organization_id: UUID, ready_at: datetime
    ) -> Asset: ...

    def mark_asset_failed(
        self,
        asset_id: UUID,
        organization_id: UUID,
        error_code: AssetErrorCode,
        error_detail: str,
        failed_at: datetime,
    ) -> Asset: ...


def detect_content_type(content: bytes) -> AssetContentType:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return AssetContentType.PNG
    if content.startswith(b"\xff\xd8\xff"):
        return AssetContentType.JPEG
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return AssetContentType.WEBP
    raise AssetContentRejectedError("Content does not match a supported image signature")


def content_metadata(
    content: bytes, declared_content_type: AssetContentType, policy: AssetIngestionPolicy
) -> tuple[AssetContentType, str, int]:
    byte_size = len(content)
    if byte_size == 0:
        raise AssetContentRejectedError("Asset content cannot be empty")
    if byte_size > policy.max_bytes:
        raise AssetContentRejectedError("Asset content exceeds the configured byte limit")
    detected = detect_content_type(content)
    if detected is not declared_content_type:
        raise AssetContentRejectedError("Declared content type does not match binary signature")
    return detected, sha256(content).hexdigest(), byte_size


def build_object_key(
    organization_id: UUID,
    project_id: UUID,
    asset_id: UUID,
    content_type: AssetContentType,
) -> str:
    extension = {
        AssetContentType.PNG: "png",
        AssetContentType.JPEG: "jpg",
        AssetContentType.WEBP: "webp",
    }[content_type]
    return (
        f"organizations/{organization_id}/projects/{project_id}/"
        f"assets/{asset_id}/original.{extension}"
    )


def validate_asset_object_key(asset: Asset) -> Asset:
    expected = build_object_key(
        asset.organization_id,
        asset.project_id,
        asset.asset_id,
        asset.content_type,
    )
    if asset.object_key != expected:
        raise ValueError("Asset object key does not match canonical asset lineage")
    return asset


def ingest_asset(
    *,
    request: AssetIngestionRequest,
    content: bytes,
    repository: AssetMetadataRepository,
    object_store: PrivateObjectStore,
    policy: AssetIngestionPolicy | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Asset:
    policy = policy or AssetIngestionPolicy()
    now = clock or (lambda: datetime.now(UTC))
    request, expected = _expected_stored_object(request, content, policy)
    pending = _ensure_pending_asset(
        repository, _build_pending_asset(request, expected, created_at=now())
    )
    if pending.status is AssetStatus.READY:
        return pending
    try:
        stored = object_store.put_if_absent(
            expected.object_key,
            content,
            content_type=expected.content_type,
            content_hash=expected.content_hash,
        )
        _verify_stored_object(expected, stored)
    except AssetStorageConflictError:
        return repository.mark_asset_failed(
            pending.asset_id,
            pending.organization_id,
            AssetErrorCode.STORAGE_CONFLICT,
            "Private object storage reported conflicting existing content",
            now(),
        )
    except AssetStorageError:
        return repository.mark_asset_failed(
            pending.asset_id,
            pending.organization_id,
            AssetErrorCode.STORAGE_UNAVAILABLE,
            "Private object storage was unavailable",
            now(),
        )
    except Exception:
        return repository.mark_asset_failed(
            pending.asset_id,
            pending.organization_id,
            AssetErrorCode.STORAGE_UNAVAILABLE,
            "Private object storage failed safely",
            now(),
        )
    try:
        return repository.mark_asset_ready(pending.asset_id, pending.organization_id, now())
    except AssetConflictError:
        existing = repository.find_asset(pending.asset_id, pending.organization_id)
        if existing is not None:
            _require_same_operation(existing, pending)
            if existing.status is AssetStatus.READY:
                return existing
        raise


def stage_asset_object(
    *,
    request: AssetIngestionRequest,
    content: bytes,
    object_store: PrivateObjectStore,
    policy: AssetIngestionPolicy | None = None,
) -> StoredObject:
    """Durably write validated bytes at their final canonical private object key."""
    policy = policy or AssetIngestionPolicy()
    _, expected = _expected_stored_object(request, content, policy)
    try:
        stored = object_store.put_if_absent(
            expected.object_key,
            content,
            content_type=expected.content_type,
            content_hash=expected.content_hash,
        )
    except AssetStorageError:
        raise
    except Exception as exc:
        raise AssetStorageError("Private object storage failed safely") from exc
    return _verify_stored_object(expected, stored)


def finalize_staged_asset(
    *,
    request: AssetIngestionRequest,
    content: bytes,
    stored_object: StoredObject,
    repository: AssetMetadataRepository,
    policy: AssetIngestionPolicy | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Asset:
    """Create and finalize metadata for bytes already durable in private storage."""
    policy = policy or AssetIngestionPolicy()
    now = clock or (lambda: datetime.now(UTC))
    request, expected = _expected_stored_object(request, content, policy)
    _verify_stored_object(expected, stored_object)
    return adopt_stored_asset(
        request=request,
        stored_metadata=expected,
        repository=repository,
        policy=policy,
        clock=now,
    )


def adopt_stored_asset(
    *,
    request: AssetIngestionRequest,
    stored_metadata: StoredObject | PrivateObjectMetadata,
    repository: AssetMetadataRepository,
    policy: AssetIngestionPolicy | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Asset:
    """Adopt exact durable-object metadata without reading or writing object bytes."""
    now = clock or (lambda: datetime.now(UTC))
    policy = policy or AssetIngestionPolicy()
    request = AssetIngestionRequest.model_validate(request)
    stored = StoredObject(
        object_key=stored_metadata.object_key,
        content_type=stored_metadata.content_type,
        content_hash=stored_metadata.content_hash,
        byte_size=stored_metadata.byte_size,
    )
    expected_key = build_object_key(
        request.organization_id,
        request.project_id,
        request.asset_id,
        request.declared_content_type,
    )
    if (
        stored.object_key != expected_key
        or stored.content_type is not request.declared_content_type
    ):
        raise AssetConflictError("Stored object metadata does not match canonical Asset lineage")
    if stored.byte_size > policy.max_bytes:
        raise AssetConflictError("Stored object exceeds the configured Asset byte limit")
    pending = _ensure_pending_asset(
        repository, _build_pending_asset(request, stored, created_at=now())
    )
    if pending.status is AssetStatus.READY:
        return pending
    try:
        return repository.mark_asset_ready(pending.asset_id, pending.organization_id, now())
    except AssetConflictError:
        existing = repository.find_asset(pending.asset_id, pending.organization_id)
        if existing is not None:
            _require_same_operation(existing, pending)
            if existing.status is AssetStatus.READY:
                return existing
        raise


def _expected_stored_object(
    request: AssetIngestionRequest,
    content: bytes,
    policy: AssetIngestionPolicy,
) -> tuple[AssetIngestionRequest, StoredObject]:
    request = AssetIngestionRequest.model_validate(request)
    content_type, content_hash, byte_size = content_metadata(
        content, request.declared_content_type, policy
    )
    return request, StoredObject(
        object_key=build_object_key(
            request.organization_id, request.project_id, request.asset_id, content_type
        ),
        content_type=content_type,
        content_hash=content_hash,
        byte_size=byte_size,
    )


def _build_pending_asset(
    request: AssetIngestionRequest,
    stored: StoredObject,
    *,
    created_at: datetime,
) -> Asset:
    return validate_asset_object_key(
        Asset(
            schema_version=ASSET_SCHEMA_VERSION,
            asset_id=request.asset_id,
            organization_id=request.organization_id,
            project_id=request.project_id,
            session_id=request.session_id,
            kind=request.kind,
            status=AssetStatus.PENDING,
            object_key=stored.object_key,
            content_type=stored.content_type,
            content_hash=stored.content_hash,
            byte_size=stored.byte_size,
            generation_run_id=request.generation_run_id,
            generation_output_ordinal=request.generation_output_ordinal,
            provider_output_id=request.provider_output_id,
            parent_asset_id=request.parent_asset_id,
            created_at=created_at,
        )
    )


def _ensure_pending_asset(repository: AssetMetadataRepository, pending: Asset) -> Asset:
    existing = repository.find_asset(pending.asset_id, pending.organization_id)
    if existing is not None:
        _require_same_operation(existing, pending)
        if existing.status is AssetStatus.FAILED:
            raise AssetConflictError("A failed asset identity cannot be reopened")
        return existing
    try:
        return repository.create_pending_asset(pending)
    except AssetConflictError:
        existing = repository.find_asset(pending.asset_id, pending.organization_id)
        if existing is None:
            raise
        _require_same_operation(existing, pending)
        if existing.status is AssetStatus.FAILED:
            raise AssetConflictError("A failed asset identity cannot be reopened") from None
        return existing


def _require_same_operation(existing: Asset, pending: Asset) -> None:
    comparable = (
        "organization_id",
        "project_id",
        "session_id",
        "kind",
        "object_key",
        "content_type",
        "content_hash",
        "byte_size",
        "generation_run_id",
        "generation_output_ordinal",
        "provider_output_id",
        "parent_asset_id",
    )
    if any(getattr(existing, field) != getattr(pending, field) for field in comparable):
        raise AssetConflictError("Asset identity was reused for different content or lineage")


def _verify_stored_object(expected_object: StoredObject, stored: StoredObject) -> StoredObject:
    try:
        stored = StoredObject.model_validate(stored)
    except Exception as exc:
        raise AssetStorageConflictError(
            "Stored object metadata does not match ingestion input"
        ) from exc
    expected = (
        expected_object.object_key,
        expected_object.content_type,
        expected_object.content_hash,
        expected_object.byte_size,
    )
    actual = (
        stored.object_key,
        stored.content_type,
        stored.content_hash,
        stored.byte_size,
    )
    if actual != expected:
        raise AssetStorageConflictError("Stored object metadata does not match ingestion input")
    return stored
