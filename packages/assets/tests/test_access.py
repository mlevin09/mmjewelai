import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_assets import (
    ASSET_ACCESS_SCHEMA_VERSION,
    Asset,
    AssetAccessContractError,
    AssetAccessPolicy,
    AssetContentType,
    AssetErrorCode,
    AssetKind,
    AssetNotReadyError,
    AssetStatus,
    SignedAssetReadAccess,
    build_object_key,
    issue_asset_read_access,
)
from jewelai_assets.access_schema import asset_access_json_schema

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
ORG_ID = UUID("10000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("10000000-0000-4000-8000-000000000003")
ASSET_ID = UUID("10000000-0000-4000-8000-000000000004")
PNG = b"\x89PNG\r\n\x1a\nminimal"


class RecordingSigner:
    def __init__(self, url="https://storage.example/signed?secret=redacted"):
        self.url = url
        self.calls = []

    def sign_read(self, object_key, expires_at):
        self.calls.append((object_key, expires_at))
        return self.url


def asset(status=AssetStatus.READY, **changes):
    values = {
        "asset_id": ASSET_ID,
        "organization_id": ORG_ID,
        "project_id": PROJECT_ID,
        "session_id": SESSION_ID,
        "kind": AssetKind.REFERENCE,
        "status": status,
        "object_key": build_object_key(ORG_ID, PROJECT_ID, ASSET_ID, AssetContentType.PNG),
        "content_type": AssetContentType.PNG,
        "content_hash": sha256(PNG).hexdigest(),
        "byte_size": len(PNG),
        "created_at": NOW,
        "ready_at": NOW if status is AssetStatus.READY else None,
        "failed_at": NOW if status is AssetStatus.FAILED else None,
        "error_code": AssetErrorCode.STORAGE_UNAVAILABLE if status is AssetStatus.FAILED else None,
        "error_detail": "Storage failed" if status is AssetStatus.FAILED else None,
    }
    values.update(changes)
    return Asset(**values)


def test_ready_asset_access_uses_exact_key_default_ttl_and_is_deterministic():
    signer = RecordingSigner()
    first = issue_asset_read_access(asset(), signer, clock=lambda: NOW)
    second = issue_asset_read_access(asset(), signer, clock=lambda: NOW)

    assert first == second
    assert first.schema_version == ASSET_ACCESS_SCHEMA_VERSION == "1.0.0"
    assert first.method == "GET"
    assert first.asset_id == ASSET_ID
    assert first.expires_at == datetime(2026, 9, 24, 12, 5, tzinfo=UTC)
    assert signer.calls == [(asset().object_key, first.expires_at)] * 2
    assert "object_key" not in first.model_dump()
    assert "organization_id" not in first.model_dump()


@pytest.mark.parametrize("status", [AssetStatus.PENDING, AssetStatus.FAILED])
def test_non_ready_asset_is_rejected_without_signing(status):
    signer = RecordingSigner()
    with pytest.raises(AssetNotReadyError, match="Only ready"):
        issue_asset_read_access(asset(status), signer, clock=lambda: NOW)
    assert signer.calls == []


def test_noncanonical_ready_asset_is_rejected_without_signing():
    signer = RecordingSigner()
    wrong_key = build_object_key(
        UUID("20000000-0000-4000-8000-000000000001"),
        PROJECT_ID,
        ASSET_ID,
        AssetContentType.PNG,
    )
    with pytest.raises(AssetAccessContractError, match="not canonical"):
        issue_asset_read_access(asset(object_key=wrong_key), signer, clock=lambda: NOW)
    assert signer.calls == []


def test_maximum_ttl_is_accepted():
    signer = RecordingSigner()
    result = issue_asset_read_access(asset(), signer, requested_ttl_seconds=900, clock=lambda: NOW)
    assert result.expires_at == datetime(2026, 9, 24, 12, 15, tzinfo=UTC)


@pytest.mark.parametrize("ttl", [0, -1, 901, True, 1.5])
def test_invalid_requested_ttl_is_rejected_without_signing(ttl):
    signer = RecordingSigner()
    with pytest.raises(AssetAccessContractError, match="TTL"):
        issue_asset_read_access(asset(), signer, requested_ttl_seconds=ttl, clock=lambda: NOW)
    assert signer.calls == []


def test_policy_rejects_invalid_bounds_and_default_above_maximum():
    with pytest.raises(ValidationError):
        AssetAccessPolicy(max_ttl_seconds=901)
    with pytest.raises(ValidationError, match="cannot exceed"):
        AssetAccessPolicy(default_ttl_seconds=600, max_ttl_seconds=300)


def test_signed_access_contract_requires_https_and_timezone_aware_expiry():
    with pytest.raises(ValidationError):
        SignedAssetReadAccess(
            asset_id=ASSET_ID, url="http://storage.example/object", expires_at=NOW
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        SignedAssetReadAccess(
            asset_id=ASSET_ID,
            url="https://storage.example/object",
            expires_at=NOW.replace(tzinfo=None),
        )


def test_issue_rejects_non_https_signer_result_without_leaking_url():
    signer = RecordingSigner("http://storage.example/signed?secret=do-not-log")
    with pytest.raises(AssetAccessContractError, match="invalid read access") as raised:
        issue_asset_read_access(asset(), signer, clock=lambda: NOW)
    assert "do-not-log" not in str(raised.value)


def test_assets_package_remains_cloud_and_framework_neutral():
    package = ROOT / "packages/assets/src/jewelai_assets"
    source = "\n".join(path.read_text() for path in package.glob("*.py"))
    for forbidden in ("google.cloud", "google.auth", "fastapi", "sqlalchemy"):
        assert forbidden not in source.lower()


def test_published_access_schema_is_valid_and_has_no_drift():
    generated = asset_access_json_schema()
    Draft202012Validator.check_schema(generated)
    assert json.loads((ROOT / "specs/asset-access/schema.json").read_text()) == generated
