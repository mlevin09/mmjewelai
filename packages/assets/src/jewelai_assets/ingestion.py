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
    request = AssetIngestionRequest.model_validate(request)
    policy = policy or AssetIngestionPolicy()
    now = clock or (lambda: datetime.now(UTC))
    content_type, content_hash, byte_size = content_metadata(
        content, request.declared_content_type, policy
    )
    pending = validate_asset_object_key(
        Asset(
            schema_version=ASSET_SCHEMA_VERSION,
            asset_id=request.asset_id,
            organization_id=request.organization_id,
            project_id=request.project_id,
            session_id=request.session_id,
            kind=request.kind,
            status=AssetStatus.PENDING,
            object_key=build_object_key(
                request.organization_id, request.project_id, request.asset_id, content_type
            ),
            content_type=content_type,
            content_hash=content_hash,
            byte_size=byte_size,
            generation_run_id=request.generation_run_id,
            generation_output_ordinal=request.generation_output_ordinal,
            provider_output_id=request.provider_output_id,
            parent_asset_id=request.parent_asset_id,
            created_at=now(),
        )
    )
    existing = repository.find_asset(request.asset_id, request.organization_id)
    if existing is not None:
        _require_same_operation(existing, pending)
        if existing.status is AssetStatus.READY:
            return existing
        if existing.status is AssetStatus.FAILED:
            raise AssetConflictError("A failed asset identity cannot be reopened")
        pending = existing
    else:
        try:
            pending = repository.create_pending_asset(pending)
        except AssetConflictError:
            existing = repository.find_asset(request.asset_id, request.organization_id)
            if existing is None:
                raise
            _require_same_operation(existing, pending)
            if existing.status is AssetStatus.READY:
                return existing
            if existing.status is AssetStatus.FAILED:
                raise AssetConflictError("A failed asset identity cannot be reopened") from None
            pending = existing
    try:
        stored = object_store.put_if_absent(
            pending.object_key,
            content,
            content_type=pending.content_type,
            content_hash=pending.content_hash,
        )
        _verify_stored_object(pending, stored)
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


def _verify_stored_object(asset: Asset, stored: StoredObject) -> None:
    expected = (asset.object_key, asset.content_type, asset.content_hash, asset.byte_size)
    actual = (
        stored.object_key,
        stored.content_type,
        stored.content_hash,
        stored.byte_size,
    )
    if actual != expected:
        raise AssetStorageConflictError("Stored object metadata does not match ingestion input")
