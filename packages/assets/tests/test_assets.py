import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_assets import (
    ASSET_SCHEMA_VERSION,
    Asset,
    AssetConflictError,
    AssetContentRejectedError,
    AssetContentType,
    AssetErrorCode,
    AssetIngestionPolicy,
    AssetIngestionRequest,
    AssetKind,
    AssetStatus,
    AssetStorageConflictError,
    AssetStorageError,
    StoredObject,
    build_object_key,
    content_metadata,
    ingest_asset,
    validate_asset_object_key,
)
from jewelai_assets.schema import asset_json_schema

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
ORG_ID = UUID("10000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("10000000-0000-4000-8000-000000000003")
ASSET_ID = UUID("10000000-0000-4000-8000-000000000004")
RUN_ID = UUID("10000000-0000-4000-8000-000000000005")
OTHER_ORG_ID = UUID("20000000-0000-4000-8000-000000000001")
OTHER_PROJECT_ID = UUID("20000000-0000-4000-8000-000000000002")
OTHER_ASSET_ID = UUID("20000000-0000-4000-8000-000000000004")
PNG = b"\x89PNG\r\n\x1a\nminimal"
JPEG = b"\xff\xd8\xffminimal"
WEBP = b"RIFF\x04\x00\x00\x00WEBPminimal"


class MemoryRepository:
    def __init__(self):
        self.assets = {}

    def find_asset(self, asset_id, organization_id):
        asset = self.assets.get(asset_id)
        return asset if asset is not None and asset.organization_id == organization_id else None

    def create_pending_asset(self, asset):
        if asset.asset_id in self.assets:
            raise AssetConflictError
        self.assets[asset.asset_id] = asset
        return asset

    def mark_asset_ready(self, asset_id, organization_id, ready_at):
        asset = self.find_asset(asset_id, organization_id)
        updated = asset.model_copy(update={"status": AssetStatus.READY, "ready_at": ready_at})
        updated = Asset.model_validate(updated)
        self.assets[asset_id] = updated
        return updated

    def mark_asset_failed(self, asset_id, organization_id, error_code, error_detail, failed_at):
        asset = self.find_asset(asset_id, organization_id)
        updated = asset.model_copy(
            update={
                "status": AssetStatus.FAILED,
                "failed_at": failed_at,
                "error_code": error_code,
                "error_detail": error_detail,
            }
        )
        updated = Asset.model_validate(updated)
        self.assets[asset_id] = updated
        return updated


class MemoryObjectStore:
    def __init__(self, failure=None):
        self.objects = {}
        self.write_count = 0
        self.failure = failure

    def put_if_absent(self, object_key, content, *, content_type, content_hash):
        self.write_count += 1
        if self.failure is not None:
            raise self.failure("controlled test failure")
        metadata = StoredObject(
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=len(content),
        )
        existing = self.objects.get(object_key)
        if existing is not None:
            existing_content, existing_metadata = existing
            if existing_content != content or existing_metadata != metadata:
                raise AssetStorageConflictError("conflict")
            return existing_metadata
        self.objects[object_key] = (content, metadata)
        return metadata


def request(**changes):
    values = {
        "asset_id": ASSET_ID,
        "organization_id": ORG_ID,
        "project_id": PROJECT_ID,
        "session_id": SESSION_ID,
        "kind": AssetKind.REFERENCE,
        "declared_content_type": AssetContentType.PNG,
    }
    values.update(changes)
    return AssetIngestionRequest(**values)


def pending_asset(**changes):
    values = {
        "asset_id": ASSET_ID,
        "organization_id": ORG_ID,
        "project_id": PROJECT_ID,
        "session_id": SESSION_ID,
        "kind": AssetKind.REFERENCE,
        "status": AssetStatus.PENDING,
        "object_key": build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.PNG),
        "content_type": AssetContentType.PNG,
        "content_hash": sha256(PNG).hexdigest(),
        "byte_size": len(PNG),
        "created_at": NOW,
    }
    values.update(changes)
    return Asset(**values)


def ticking_clock():
    values = iter((NOW, NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))
    return lambda: next(values)


def test_contract_is_frozen_forbids_extra_and_has_stable_version():
    asset = pending_asset()
    assert asset.schema_version == ASSET_SCHEMA_VERSION == "1.0.0"
    with pytest.raises(ValidationError):
        Asset(**asset.model_dump(), unexpected=True)
    with pytest.raises(ValidationError):
        asset.status = AssetStatus.READY


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "ready"},
        {"status": "pending", "ready_at": NOW},
        {"status": "failed", "failed_at": NOW},
        {
            "status": "failed",
            "failed_at": NOW,
            "error_code": "storage_unavailable",
        },
        {"parent_asset_id": ASSET_ID},
        {"kind": "generated"},
    ],
)
def test_asset_rejects_invalid_lifecycle_and_lineage(changes):
    with pytest.raises(ValidationError):
        pending_asset(**changes)


def test_reference_and_generated_request_lineage_is_explicit():
    with pytest.raises(ValidationError):
        request(generation_run_id=RUN_ID)
    generated = request(
        kind="generated",
        generation_run_id=RUN_ID,
        generation_output_ordinal=1,
        provider_output_id="output-1",
    )
    assert generated.kind is AssetKind.GENERATED
    with pytest.raises(ValidationError):
        request(declared_content_type="image/svg+xml")
    with pytest.raises(ValidationError):
        request(declared_content_type="application/octet-stream")


@pytest.mark.parametrize(
    "content,declared",
    [(PNG, AssetContentType.PNG), (JPEG, AssetContentType.JPEG), (WEBP, AssetContentType.WEBP)],
)
def test_supported_signatures_hash_and_size_are_authoritative(content, declared):
    detected, digest, size = content_metadata(content, declared, AssetIngestionPolicy())
    assert detected is declared
    assert digest == sha256(content).hexdigest()
    assert digest == digest.lower()
    assert size == len(content)


@pytest.mark.parametrize(
    "content,declared",
    [
        (b"", AssetContentType.PNG),
        (JPEG, AssetContentType.PNG),
        (b"<html>bad</html>", AssetContentType.PNG),
        (b"<svg></svg>", AssetContentType.PNG),
        (b"arbitrary", AssetContentType.PNG),
    ],
)
def test_content_rejection(content, declared):
    with pytest.raises(AssetContentRejectedError):
        content_metadata(content, declared, AssetIngestionPolicy())


def test_oversized_content_is_rejected():
    with pytest.raises(AssetContentRejectedError):
        content_metadata(PNG, AssetContentType.PNG, AssetIngestionPolicy(max_bytes=len(PNG) - 1))


@pytest.mark.parametrize(
    "content_type,extension",
    [
        (AssetContentType.PNG, "png"),
        (AssetContentType.JPEG, "jpg"),
        (AssetContentType.WEBP, "webp"),
    ],
)
def test_object_key_is_deterministic_scoped_and_safe(content_type, extension):
    key = build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, content_type)
    assert key == (
        f"organizations/{ORG_ID}/projects/{PROJECT_ID}/assets/{ASSET_ID}/original.{extension}"
    )
    assert ".." not in key and "://" not in key and "?" not in key


@pytest.mark.parametrize(
    "content_type",
    [AssetContentType.PNG, AssetContentType.JPEG, AssetContentType.WEBP],
)
def test_canonical_object_key_validation_accepts_supported_content_types(content_type):
    asset = pending_asset(
        content_type=content_type,
        object_key=build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, content_type),
    )
    assert validate_asset_object_key(asset) is asset


@pytest.mark.parametrize(
    "changes",
    [
        {"object_key": build_object_key(OTHER_ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.PNG)},
        {"object_key": build_object_key(ORG_ID, OTHER_PROJECT_ID, ASSET_ID, AssetContentType.PNG)},
        {"object_key": build_object_key(ORG_ID, PROJECT_ID, OTHER_ASSET_ID, AssetContentType.PNG)},
        {"object_key": build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.JPEG)},
        {
            "content_type": AssetContentType.JPEG,
            "object_key": build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.WEBP),
        },
    ],
)
def test_canonical_object_key_validation_rejects_lineage_or_extension_mismatch(changes):
    with pytest.raises(ValueError, match="canonical asset lineage"):
        validate_asset_object_key(pending_asset(**changes))


@pytest.mark.parametrize(
    "kind,lineage",
    [
        (AssetKind.REFERENCE, {}),
        (
            AssetKind.GENERATED,
            {
                "generation_run_id": RUN_ID,
                "generation_output_ordinal": 1,
                "provider_output_id": "output-1",
            },
        ),
    ],
)
def test_reference_and_generated_assets_share_object_key_invariant(kind, lineage):
    asset = pending_asset(kind=kind, **lineage)
    assert validate_asset_object_key(asset) is asset


def test_memory_store_is_create_only_and_idempotent():
    store = MemoryObjectStore()
    key = build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.PNG)
    digest = sha256(PNG).hexdigest()
    first = store.put_if_absent(key, PNG, content_type=AssetContentType.PNG, content_hash=digest)
    second = store.put_if_absent(key, PNG, content_type=AssetContentType.PNG, content_hash=digest)
    assert first == second
    assert store.write_count == 2
    with pytest.raises(AssetStorageConflictError):
        store.put_if_absent(
            key,
            PNG + b"different",
            content_type=AssetContentType.PNG,
            content_hash=sha256(PNG + b"different").hexdigest(),
        )


def test_reference_ingestion_succeeds_without_metadata_bytes_and_retry_skips_write():
    repository = MemoryRepository()
    store = MemoryObjectStore()
    first = ingest_asset(
        request=request(),
        content=PNG,
        repository=repository,
        object_store=store,
        clock=ticking_clock(),
    )
    second = ingest_asset(
        request=request(),
        content=PNG,
        repository=repository,
        object_store=store,
        clock=lambda: NOW + timedelta(minutes=1),
    )
    assert first == second
    assert first.status is AssetStatus.READY
    assert first.content_hash == sha256(PNG).hexdigest()
    assert first.byte_size == len(PNG)
    assert first.object_key == build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.PNG)
    assert store.objects[first.object_key][0] == PNG
    assert b"minimal" not in json.dumps(first.model_dump(mode="json")).encode()
    assert store.write_count == 1


def test_conflicting_same_id_retry_preserves_original():
    repository = MemoryRepository()
    store = MemoryObjectStore()
    original = ingest_asset(
        request=request(),
        content=PNG,
        repository=repository,
        object_store=store,
        clock=ticking_clock(),
    )
    with pytest.raises(AssetConflictError):
        ingest_asset(
            request=request(declared_content_type="image/jpeg"),
            content=JPEG,
            repository=repository,
            object_store=store,
            clock=lambda: NOW + timedelta(minutes=1),
        )
    assert repository.assets[ASSET_ID] == original


def test_pending_asset_resumes_create_only_write_after_interruption():
    repository = MemoryRepository()
    pending = pending_asset()
    repository.assets[pending.asset_id] = pending
    store = MemoryObjectStore()
    result = ingest_asset(
        request=request(),
        content=PNG,
        repository=repository,
        object_store=store,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    assert result.status is AssetStatus.READY
    assert store.write_count == 1


@pytest.mark.parametrize(
    "failure,code",
    [
        (AssetStorageError, AssetErrorCode.STORAGE_UNAVAILABLE),
        (AssetStorageConflictError, AssetErrorCode.STORAGE_CONFLICT),
        (RuntimeError, AssetErrorCode.STORAGE_UNAVAILABLE),
    ],
)
def test_storage_failure_persists_safe_terminal_failure(failure, code):
    result = ingest_asset(
        request=request(),
        content=PNG,
        repository=MemoryRepository(),
        object_store=MemoryObjectStore(failure),
        clock=ticking_clock(),
    )
    assert result.status is AssetStatus.FAILED
    assert result.failed_at is not None and result.ready_at is None
    assert result.error_code is code
    assert "controlled test failure" not in result.error_detail


def test_published_schema_is_valid_and_has_no_drift():
    generated = asset_json_schema()
    Draft202012Validator.check_schema(generated)
    assert json.loads((ROOT / "specs/assets/schema.json").read_text()) == generated
