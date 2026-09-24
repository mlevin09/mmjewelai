from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from google.api_core.exceptions import PreconditionFailed
from jewelai_assets import (
    Asset,
    AssetAccessUnavailableError,
    AssetConflictError,
    AssetContentType,
    AssetIngestionRequest,
    AssetKind,
    AssetStatus,
    AssetStorageConflictError,
    AssetStorageError,
    StoredObject,
    build_object_key,
    ingest_asset,
    issue_asset_read_access,
)

from jewelai_assets_gcs import (
    JEWELAI_SHA256_METADATA_KEY,
    GcsAssetStorageConfig,
    GcsPrivateObjectAccessSigner,
    GcsPrivateObjectStore,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
ORG_ID = UUID("10000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("10000000-0000-4000-8000-000000000003")
ASSET_ID = UUID("10000000-0000-4000-8000-000000000004")
PNG = b"\x89PNG\r\n\x1a\nminimal"
CONTENT_HASH = sha256(PNG).hexdigest()
OBJECT_KEY = build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.PNG)


class FakeBlob:
    def __init__(
        self,
        name,
        *,
        content_type=None,
        size=None,
        metadata=None,
        upload_error=None,
        signed_url="https://storage.googleapis.test/signed?secret=redacted",
        signing_error=None,
    ):
        self.name = name
        self.content_type = content_type
        self.size = size
        self.metadata = metadata
        self.upload_error = upload_error
        self.signed_url = signed_url
        self.signing_error = signing_error
        self.upload_calls = []
        self.sign_calls = []
        self.public_calls = 0

    def upload_from_string(self, content, **kwargs):
        self.upload_calls.append((content, kwargs))
        if self.upload_error is not None:
            raise self.upload_error

    def generate_signed_url(self, **kwargs):
        self.sign_calls.append(kwargs)
        if self.signing_error is not None:
            raise self.signing_error
        return self.signed_url

    def make_public(self):
        self.public_calls += 1
        raise AssertionError("Private assets must never be made public")


class FakeBucket:
    def __init__(self, write_blob, existing_blob=None):
        self.write_blob = write_blob
        self.existing_blob = existing_blob
        self.blob_calls = []
        self.get_blob_calls = []

    def blob(self, object_key):
        self.blob_calls.append(object_key)
        return self.write_blob

    def get_blob(self, object_key):
        self.get_blob_calls.append(object_key)
        return self.existing_blob


class FakeClient:
    def __init__(self, bucket):
        self._bucket = bucket
        self.bucket_calls = []
        self.create_bucket_calls = []

    def bucket(self, bucket_name):
        self.bucket_calls.append(bucket_name)
        return self._bucket

    def create_bucket(self, *args, **kwargs):
        self.create_bucket_calls.append((args, kwargs))
        raise AssertionError("The adapter must not provision buckets")


class MemoryRepository:
    def __init__(self):
        self.assets = {}

    def find_asset(self, asset_id, organization_id):
        found = self.assets.get(asset_id)
        return found if found is not None and found.organization_id == organization_id else None

    def create_pending_asset(self, asset):
        if asset.asset_id in self.assets:
            raise AssetConflictError("duplicate")
        self.assets[asset.asset_id] = asset
        return asset

    def mark_asset_ready(self, asset_id, organization_id, ready_at):
        current = self.find_asset(asset_id, organization_id)
        updated = Asset.model_validate(
            current.model_copy(update={"status": AssetStatus.READY, "ready_at": ready_at})
        )
        self.assets[asset_id] = updated
        return updated

    def mark_asset_failed(self, asset_id, organization_id, error_code, error_detail, failed_at):
        current = self.find_asset(asset_id, organization_id)
        updated = Asset.model_validate(
            current.model_copy(
                update={
                    "status": AssetStatus.FAILED,
                    "failed_at": failed_at,
                    "error_code": error_code,
                    "error_detail": error_detail,
                }
            )
        )
        self.assets[asset_id] = updated
        return updated


def config():
    return GcsAssetStorageConfig(bucket_name="jewelai-private-assets", project_id="jewelai-prod")


def ready_asset():
    return Asset(
        asset_id=ASSET_ID,
        organization_id=ORG_ID,
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        kind=AssetKind.REFERENCE,
        status=AssetStatus.READY,
        object_key=OBJECT_KEY,
        content_type=AssetContentType.PNG,
        content_hash=CONTENT_HASH,
        byte_size=len(PNG),
        created_at=NOW,
        ready_at=NOW,
    )


@pytest.mark.parametrize("bucket_name", ["", "gs://bucket", "https://bucket", "bucket/path"])
def test_config_rejects_non_bucket_values(bucket_name):
    with pytest.raises(ValueError, match="bucket"):
        GcsAssetStorageConfig(bucket_name=bucket_name)


def test_new_object_write_is_private_create_only_and_carries_integrity_metadata():
    blob = FakeBlob(OBJECT_KEY)
    bucket = FakeBucket(blob)
    client = FakeClient(bucket)
    store = GcsPrivateObjectStore(config(), client=client)

    result = store.put_if_absent(
        OBJECT_KEY,
        PNG,
        content_type=AssetContentType.PNG,
        content_hash=CONTENT_HASH,
    )

    assert client.bucket_calls == ["jewelai-private-assets"]
    assert client.create_bucket_calls == []
    assert bucket.blob_calls == [OBJECT_KEY]
    assert bucket.get_blob_calls == []
    assert blob.upload_calls == [
        (
            PNG,
            {"content_type": "image/png", "if_generation_match": 0},
        )
    ]
    assert blob.metadata == {JEWELAI_SHA256_METADATA_KEY: CONTENT_HASH}
    assert blob.public_calls == 0
    assert result == StoredObject(
        object_key=OBJECT_KEY,
        content_type=AssetContentType.PNG,
        content_hash=CONTENT_HASH,
        byte_size=len(PNG),
    )


def test_existing_matching_object_is_idempotent_without_overwrite_or_download():
    upload = FakeBlob(OBJECT_KEY, upload_error=PreconditionFailed("already exists"))
    existing = FakeBlob(
        OBJECT_KEY,
        content_type="image/png",
        size=len(PNG),
        metadata={JEWELAI_SHA256_METADATA_KEY: CONTENT_HASH},
    )
    bucket = FakeBucket(upload, existing)
    store = GcsPrivateObjectStore(config(), client=FakeClient(bucket))

    result = store.put_if_absent(
        OBJECT_KEY,
        PNG,
        content_type=AssetContentType.PNG,
        content_hash=CONTENT_HASH,
    )

    assert result.content_hash == CONTENT_HASH
    assert len(upload.upload_calls) == 1
    assert bucket.get_blob_calls == [OBJECT_KEY]
    assert not hasattr(existing, "download_as_bytes")


@pytest.mark.parametrize(
    "existing",
    [
        FakeBlob(
            OBJECT_KEY,
            content_type="image/png",
            size=len(PNG),
            metadata={JEWELAI_SHA256_METADATA_KEY: "f" * 64},
        ),
        FakeBlob(
            OBJECT_KEY,
            content_type="image/png",
            size=len(PNG) + 1,
            metadata={JEWELAI_SHA256_METADATA_KEY: CONTENT_HASH},
        ),
        FakeBlob(
            OBJECT_KEY,
            content_type="image/jpeg",
            size=len(PNG),
            metadata={JEWELAI_SHA256_METADATA_KEY: CONTENT_HASH},
        ),
    ],
)
def test_existing_conflicting_object_fails_closed(existing):
    upload = FakeBlob(OBJECT_KEY, upload_error=PreconditionFailed("already exists"))
    store = GcsPrivateObjectStore(config(), client=FakeClient(FakeBucket(upload, existing)))
    with pytest.raises(AssetStorageConflictError, match="conflicts"):
        store.put_if_absent(
            OBJECT_KEY,
            PNG,
            content_type=AssetContentType.PNG,
            content_hash=CONTENT_HASH,
        )
    assert len(upload.upload_calls) == 1


def test_write_and_metadata_failures_map_to_safe_storage_errors():
    secret = "credential-secret-response"
    upload = FakeBlob(OBJECT_KEY, upload_error=PermissionError(secret))
    store = GcsPrivateObjectStore(config(), client=FakeClient(FakeBucket(upload)))
    with pytest.raises(AssetStorageError, match="create-only write failed") as raised:
        store.put_if_absent(
            OBJECT_KEY,
            PNG,
            content_type=AssetContentType.PNG,
            content_hash=CONTENT_HASH,
        )
    assert secret not in str(raised.value)

    upload = FakeBlob(OBJECT_KEY, upload_error=PreconditionFailed("already exists"))
    bucket = FakeBucket(upload)
    bucket.get_blob = lambda _: (_ for _ in ()).throw(TimeoutError(secret))
    store = GcsPrivateObjectStore(config(), client=FakeClient(bucket))
    with pytest.raises(AssetStorageError, match="metadata verification") as raised:
        store.put_if_absent(
            OBJECT_KEY,
            PNG,
            content_type=AssetContentType.PNG,
            content_hash=CONTENT_HASH,
        )
    assert secret not in str(raised.value)


def test_ingestion_uses_gcs_store_without_changing_provider_neutral_semantics():
    blob = FakeBlob(OBJECT_KEY)
    store = GcsPrivateObjectStore(config(), client=FakeClient(FakeBucket(blob)))
    repository = MemoryRepository()
    result = ingest_asset(
        request=AssetIngestionRequest(
            asset_id=ASSET_ID,
            organization_id=ORG_ID,
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            kind=AssetKind.REFERENCE,
            declared_content_type=AssetContentType.PNG,
        ),
        content=PNG,
        repository=repository,
        object_store=store,
        clock=iter((NOW, NOW + timedelta(seconds=1))).__next__,
    )
    assert result.status is AssetStatus.READY
    assert result.object_key == OBJECT_KEY
    assert blob.upload_calls[0][1]["if_generation_match"] == 0


def test_v4_get_signing_uses_configured_bucket_exact_key_and_expiration():
    blob = FakeBlob(OBJECT_KEY)
    bucket = FakeBucket(blob)
    client = FakeClient(bucket)
    signer = GcsPrivateObjectAccessSigner(config(), client=client)
    expires_at = NOW + timedelta(minutes=5)

    result = signer.sign_read(OBJECT_KEY, expires_at)

    assert result.startswith("https://")
    assert client.bucket_calls == ["jewelai-private-assets"]
    assert client.create_bucket_calls == []
    assert bucket.blob_calls == [OBJECT_KEY]
    assert blob.sign_calls == [
        {
            "version": "v4",
            "expiration": expires_at,
            "method": "GET",
            "scheme": "https",
        }
    ]
    assert blob.public_calls == 0


def test_signer_rejects_arbitrary_path_before_sdk_call():
    blob = FakeBlob(OBJECT_KEY)
    bucket = FakeBucket(blob)
    signer = GcsPrivateObjectAccessSigner(config(), client=FakeClient(bucket))
    with pytest.raises(AssetAccessUnavailableError, match="unavailable"):
        signer.sign_read("customer-selected/path", NOW + timedelta(minutes=5))
    assert bucket.blob_calls == []


@pytest.mark.parametrize(
    "signed_url",
    [
        "http://storage.googleapis.test/signed?secret=do-not-log",
        "https:///missing-host",
        "not-a-url",
    ],
)
def test_non_https_signing_result_is_rejected_without_secret_leak(signed_url):
    blob = FakeBlob(OBJECT_KEY, signed_url=signed_url)
    signer = GcsPrivateObjectAccessSigner(config(), client=FakeClient(FakeBucket(blob)))
    with pytest.raises(AssetAccessUnavailableError, match="invalid URL") as raised:
        signer.sign_read(OBJECT_KEY, NOW + timedelta(minutes=5))
    assert "do-not-log" not in str(raised.value)


def test_signing_failure_maps_to_safe_access_error():
    secret = "private-signing-credential"
    blob = FakeBlob(OBJECT_KEY, signing_error=RuntimeError(secret))
    signer = GcsPrivateObjectAccessSigner(config(), client=FakeClient(FakeBucket(blob)))
    with pytest.raises(AssetAccessUnavailableError, match="unavailable") as raised:
        signer.sign_read(OBJECT_KEY, NOW + timedelta(minutes=5))
    assert secret not in str(raised.value)


def test_ready_access_integration_passes_only_asset_owned_key_to_gcs_signer():
    blob = FakeBlob(OBJECT_KEY)
    signer = GcsPrivateObjectAccessSigner(config(), client=FakeClient(FakeBucket(blob)))
    result = issue_asset_read_access(ready_asset(), signer, clock=lambda: NOW)
    assert result.asset_id == ASSET_ID
    assert result.url == blob.signed_url
    assert result.expires_at == NOW + timedelta(minutes=5)
    assert blob.sign_calls[0]["method"] == "GET"
