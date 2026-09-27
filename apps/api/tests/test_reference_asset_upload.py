from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from conftest import (
    NOW,
    FakePrivateObjectStore,
    FakeTokenVerifier,
    create_hierarchy,
)
from fastapi.testclient import TestClient
from jewelai_assets import AssetStorageConflictError, AssetStorageError
from jewelai_assets_gcs import GcsAssetStorageConfig
from jewelai_auth import AuthenticationUnavailableError
from jewelai_persistence import create_session_factory
from jewelai_persistence.models import (
    AssetRow,
    GenerationDispatchOutboxRow,
    GenerationRunRow,
    MessageRow,
    PromptRevisionRow,
    SpecificationRevisionRow,
)
from sqlalchemy import select

from jewelai_api import create_app
from jewelai_api.settings import RuntimeSettings

ROOT = Path(__file__).resolve().parents[3]
PNG = b"\x89PNG\r\n\x1a\nreference-png"
JPEG = b"\xff\xd8\xffreference-jpeg"
WEBP = b"RIFF\x10\x00\x00\x00WEBPreference-webp"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def upload(
    client,
    session_id,
    organization_id,
    *,
    content=PNG,
    content_type="image/png",
    filename="reference.png",
    headers=None,
):
    request_headers = {"X-Organization-ID": organization_id}
    if headers:
        request_headers.update(headers)
    return client.post(
        f"/sessions/{session_id}/assets",
        headers=request_headers,
        files={"file": (filename, content, content_type)},
    )


def test_png_upload_creates_ready_reference_asset_with_server_owned_lineage(
    client, app, asset_object_store
):
    organization_id, project_id, session_response = create_hierarchy(client)
    session = session_response.json()
    expected_asset_id = UUID("11111111-1111-4111-8111-111111111111")
    app.state.service._uuid = lambda: expected_asset_id

    response = upload(client, session["session_id"], organization_id, filename="evil.exe")

    assert response.status_code == 201
    payload = response.json()
    assert payload == {
        "schema_version": "1.0.0",
        "asset_id": str(expected_asset_id),
        "session_id": session["session_id"],
        "kind": "reference",
        "status": "ready",
        "content_type": "image/png",
        "content_hash": sha256(PNG).hexdigest(),
        "byte_size": len(PNG),
        "generation_run_id": None,
        "generation_output_ordinal": None,
        "parent_asset_id": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "ready_at": NOW.isoformat().replace("+00:00", "Z"),
        "failed_at": None,
        "error_code": None,
        "error_detail": None,
    }
    assert "object_key" not in payload
    assert "filename" not in payload
    assert "bucket" not in payload
    assert "url" not in payload
    assert "signed_url" not in payload
    assert len(asset_object_store.calls) == 1
    object_key, content, content_type, content_hash = asset_object_store.calls[0]
    assert object_key == (
        f"organizations/{organization_id}/projects/{project_id}/"
        f"assets/{expected_asset_id}/original.png"
    )
    assert content == PNG
    assert content_type == "image/png"
    assert content_hash == sha256(PNG).hexdigest()


@pytest.mark.parametrize(
    ("content", "content_type", "extension"),
    [(JPEG, "image/jpeg", "jpg"), (WEBP, "image/webp", "webp")],
)
def test_jpeg_and_webp_uploads_are_supported(
    client, asset_object_store, content, content_type, extension
):
    organization_id, project_id, session_response = create_hierarchy(client)
    response = upload(
        client,
        session_response.json()["session_id"],
        organization_id,
        content=content,
        content_type=content_type,
        filename="misleading.png",
    )
    assert response.status_code == 201
    assert response.json()["content_type"] == content_type
    assert asset_object_store.calls[-1][0].startswith(
        f"organizations/{organization_id}/projects/{project_id}/assets/"
    )
    assert asset_object_store.calls[-1][0].endswith(f"/original.{extension}")


@pytest.mark.parametrize(
    ("content", "content_type", "status", "error"),
    [
        (JPEG, "image/png", 422, "invalid_asset_content"),
        (b"not-an-image", "image/png", 422, "invalid_asset_content"),
        (b"", "image/png", 422, "invalid_asset_content"),
        (b"GIF89a", "image/gif", 415, "unsupported_asset_media_type"),
    ],
)
def test_invalid_content_is_rejected_before_asset_or_storage(
    client, app, asset_object_store, content, content_type, status, error
):
    organization_id, _, session_response = create_hierarchy(client)
    response = upload(
        client,
        session_response.json()["session_id"],
        organization_id,
        content=content,
        content_type=content_type,
    )
    assert response.status_code == status
    assert response.json()["error"] == error
    assert asset_object_store.calls == []
    assert (
        app.state.service.repository.list_assets(
            UUID(session_response.json()["session_id"]), UUID(organization_id)
        )
        == ()
    )


def test_missing_declared_media_type_is_415(client, asset_object_store):
    organization_id, _, session_response = create_hierarchy(client)
    boundary = "jewelai-upload-boundary"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="reference"\r\n'
            "\r\n"
        ).encode()
        + PNG
        + f"\r\n--{boundary}--\r\n".encode()
    )
    response = client.post(
        f"/sessions/{session_response.json()['session_id']}/assets",
        headers={
            "X-Organization-ID": organization_id,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        content=body,
    )
    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_asset_media_type"
    assert asset_object_store.calls == []


def test_multiple_files_are_rejected_without_storage(client, asset_object_store):
    organization_id, _, session_response = create_hierarchy(client)
    response = client.post(
        f"/sessions/{session_response.json()['session_id']}/assets",
        headers={"X-Organization-ID": organization_id},
        files=[
            ("file", ("one.png", PNG, "image/png")),
            ("file", ("two.png", PNG, "image/png")),
        ],
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_asset_content"
    assert asset_object_store.calls == []


def test_oversized_upload_is_rejected_before_service_and_exact_limit_is_allowed(
    engine, asset_access_signer, generation_task_publisher
):
    store = FakePrivateObjectStore()
    application = create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
            asset_upload_max_bytes=16,
            http_max_request_bytes=16 + 64 * 1024,
        ),
        engine=engine,
        clock=lambda: NOW,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=asset_access_signer,
        asset_object_store=store,
        generation_task_publisher=generation_task_publisher,
    )
    with TestClient(application) as limited:
        limited.headers["Authorization"] = "Bearer test-owner-limited"
        organization_id, _, session_response = create_hierarchy(limited)
        session_id = session_response.json()["session_id"]
        oversized = upload(
            limited,
            session_id,
            organization_id,
            content=PNG[:8] + b"x" * 9,
        )
        assert oversized.status_code == 413
        assert oversized.json() == {
            "error": "asset_too_large",
            "detail": "Uploaded Asset exceeds the configured size limit",
        }
        assert store.calls == []
        assert (
            application.state.service.repository.list_assets(
                UUID(session_id), UUID(organization_id)
            )
            == ()
        )

        exact = upload(
            limited,
            session_id,
            organization_id,
            content=PNG[:8] + b"x" * 8,
        )
        assert exact.status_code == 201
        assert exact.json()["byte_size"] == 16


@pytest.mark.parametrize("filename", ["evil.exe", "../../../photo.png", "foo.jpg"])
def test_filename_has_no_authority(client, asset_object_store, filename):
    organization_id, _, session_response = create_hierarchy(client)
    response = upload(
        client,
        session_response.json()["session_id"],
        organization_id,
        filename=filename,
    )
    assert response.status_code == 201
    assert response.json()["content_type"] == "image/png"
    assert filename not in response.text
    assert asset_object_store.calls[-1][0].endswith("/original.png")


def test_upload_requires_bearer_and_header_alone_is_not_authorization(client, asset_object_store):
    organization_id, _, session_response = create_hierarchy(client)
    session_id = session_response.json()["session_id"]
    missing = upload(
        client,
        session_id,
        organization_id,
        headers={"Authorization": ""},
    )
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert asset_object_store.calls == []


def test_upload_maps_authentication_service_failure_to_503_without_storage(
    engine, asset_access_signer, generation_task_publisher
):
    class UnavailableVerifier:
        def verify(self, token):
            raise AuthenticationUnavailableError("Identity key service is unavailable")

    store = FakePrivateObjectStore()
    application = create_app(
        RuntimeSettings(database_url="sqlite+pysqlite://", repository_root=ROOT),
        engine=engine,
        token_verifier=UnavailableVerifier(),
        asset_access_signer=asset_access_signer,
        asset_object_store=store,
        generation_task_publisher=generation_task_publisher,
    )
    with TestClient(application) as isolated:
        response = upload(
            isolated,
            UUID(int=1),
            str(UUID(int=2)),
            headers=auth("test-unavailable"),
        )
    assert response.status_code == 503
    assert response.json()["error"] == "authentication_unavailable"
    assert store.calls == []


@pytest.mark.parametrize("role", ["admin", "member"])
def test_admin_and_member_may_upload_reference_assets(client, asset_object_store, role):
    organization_id, _, session_response = create_hierarchy(client)
    principal = client.get("/me", headers=auth(f"test-{role}-uploader")).json()
    added = client.post(
        f"/organizations/{organization_id}/memberships",
        json={"principal_id": principal["principal_id"], "role": role},
    )
    assert added.status_code == 201
    response = upload(
        client,
        session_response.json()["session_id"],
        organization_id,
        headers=auth(f"test-{role}-uploader"),
    )
    assert response.status_code == 201
    assert response.json()["kind"] == "reference"
    assert len(asset_object_store.calls) == 1


def test_revoked_or_cross_tenant_member_cannot_reach_storage(client, asset_object_store):
    organization_id, _, session_response = create_hierarchy(client)
    session_id = session_response.json()["session_id"]
    member = client.get("/me", headers=auth("test-revoked-uploader")).json()
    client.post(
        f"/organizations/{organization_id}/memberships",
        json={"principal_id": member["principal_id"], "role": "member"},
    )
    selected = auth("test-revoked-uploader")
    assert upload(client, session_id, organization_id, headers=selected).status_code == 201
    calls = len(asset_object_store.calls)
    client.delete(f"/organizations/{organization_id}/memberships/{member['principal_id']}")
    revoked = upload(client, session_id, organization_id, headers=selected)
    assert revoked.status_code == 404
    assert len(asset_object_store.calls) == calls

    foreign = client.post("/organizations", json={"name": "Foreign tenant"}).json()
    foreign_attempt = upload(
        client,
        session_id,
        foreign["organization_id"],
        headers=selected,
    )
    assert foreign_attempt.status_code == 404
    assert len(asset_object_store.calls) == calls


def test_unknown_session_cannot_reach_storage(client, asset_object_store):
    organization_id = client.post("/organizations", json={"name": "Upload scope"}).json()[
        "organization_id"
    ]
    response = upload(
        client,
        UUID(int=999),
        organization_id,
        content=PNG + b"oversized-for-any-small-policy-does-not-matter",
        content_type="image/gif",
    )
    assert response.status_code == 404
    assert asset_object_store.calls == []


@pytest.mark.parametrize(
    "error",
    [
        AssetStorageError("bucket secret and object key"),
        AssetStorageConflictError("conflicting internal object key"),
    ],
)
def test_storage_failures_are_safely_mapped_to_503(client, app, asset_object_store, error):
    organization_id, _, session_response = create_hierarchy(client)
    asset_object_store.error = error
    response = upload(client, session_response.json()["session_id"], organization_id)
    assert response.status_code == 503
    assert response.json() == {
        "error": "asset_upload_unavailable",
        "detail": "Private Asset storage is temporarily unavailable",
    }
    assert "secret" not in response.text
    assets = app.state.service.repository.list_assets(
        UUID(session_response.json()["session_id"]), UUID(organization_id)
    )
    assert len(assets) == 1
    assert assets[0].status == "failed"


def test_upload_is_listed_gettable_and_uses_existing_signed_read_flow(client, asset_access_signer):
    organization_id, _, session_response = create_hierarchy(client)
    session_id = session_response.json()["session_id"]
    uploaded = upload(client, session_id, organization_id)
    assert uploaded.status_code == 201
    payload = uploaded.json()
    headers = {"X-Organization-ID": organization_id}
    listed = client.get(f"/sessions/{session_id}/assets", headers=headers)
    assert listed.json()["assets"] == [payload]
    fetched = client.get(f"/sessions/{session_id}/assets/{payload['asset_id']}", headers=headers)
    assert fetched.json() == payload
    access = client.post(
        f"/sessions/{session_id}/assets/{payload['asset_id']}/access",
        headers=headers,
        json={"ttl_seconds": 60},
    )
    assert access.status_code == 200
    assert access.json()["url"] == asset_access_signer.url
    assert asset_access_signer.calls[0][1] == NOW + timedelta(seconds=60)


def test_upload_has_no_message_revision_prompt_or_generation_side_effect(client, app):
    organization_id, _, session_response = create_hierarchy(client)
    session_id = session_response.json()["session_id"]
    row_types = (
        SpecificationRevisionRow,
        MessageRow,
        PromptRevisionRow,
        GenerationRunRow,
        GenerationDispatchOutboxRow,
    )
    with create_session_factory(app.state.engine)() as db:
        before = tuple(len(db.scalars(select(row_type)).all()) for row_type in row_types)
    assert upload(client, session_id, organization_id).status_code == 201
    with create_session_factory(app.state.engine)() as db:
        after = tuple(len(db.scalars(select(row_type)).all()) for row_type in row_types)
        assets = db.scalars(select(AssetRow)).all()
    assert after == before
    assert len(assets) == 1


def test_reference_upload_openapi_is_multipart_bearer_and_asset_response(client):
    document = client.app.openapi()
    operation = document["paths"]["/sessions/{session_id}/assets"]["post"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert set(operation["requestBody"]["content"]) == {"multipart/form-data"}
    assert operation["requestBody"]["required"] is True
    assert operation["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "AssetResponse"
    )
    assert "get" in document["paths"]["/sessions/{session_id}/assets"]


def test_production_composition_builds_gcs_store_without_network(
    monkeypatch, engine, asset_access_signer, generation_task_publisher
):
    captured = []
    store = FakePrivateObjectStore()

    def fake_constructor(config):
        captured.append(config)
        return store

    monkeypatch.setattr("jewelai_api.app.GcsPrivateObjectStore", fake_constructor)
    config = GcsAssetStorageConfig(
        bucket_name="jewelai-assets-prod",
        project_id="jewelai-prod",
        signing_service_account_email="signer@jewelai-prod.iam.gserviceaccount.com",
    )
    application = create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
            asset_signing=config,
        ),
        engine=engine,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=asset_access_signer,
        generation_task_publisher=generation_task_publisher,
    )
    assert application.state.service._asset_object_store is store
    assert captured == [config]


def test_app_factory_requires_gcs_configuration_without_injected_store(
    engine, asset_access_signer, generation_task_publisher
):
    with pytest.raises(ValueError, match="GCS Asset storage configuration"):
        create_app(
            RuntimeSettings(database_url="sqlite+pysqlite://", repository_root=ROOT),
            engine=engine,
            token_verifier=FakeTokenVerifier(),
            asset_access_signer=asset_access_signer,
            generation_task_publisher=generation_task_publisher,
        )
