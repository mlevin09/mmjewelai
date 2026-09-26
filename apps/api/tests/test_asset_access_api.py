from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from conftest import NOW, FakeTokenVerifier, create_hierarchy
from jewelai_assets import (
    Asset,
    AssetContentType,
    AssetErrorCode,
    AssetKind,
    AssetStatus,
    build_object_key,
)
from jewelai_assets_gcs import GcsAssetStorageConfig
from jewelai_persistence.models import AssetRow

from jewelai_api import create_app
from jewelai_api.settings import RuntimeSettings


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def persist_asset(app, organization_id, project_id, session_id, *, terminal="ready"):
    asset_id = uuid4()
    asset = Asset(
        asset_id=asset_id,
        organization_id=UUID(organization_id),
        project_id=UUID(project_id),
        session_id=UUID(session_id),
        kind=AssetKind.REFERENCE,
        status=AssetStatus.PENDING,
        object_key=build_object_key(
            UUID(organization_id),
            UUID(project_id),
            asset_id,
            AssetContentType.PNG,
        ),
        content_type=AssetContentType.PNG,
        content_hash="a" * 64,
        byte_size=128,
        created_at=NOW,
    )
    app.state.service.repository.create_pending_asset(asset)
    if terminal == "ready":
        return app.state.service.repository.mark_asset_ready(
            asset_id, UUID(organization_id), NOW + timedelta(seconds=1)
        )
    if terminal == "failed":
        return app.state.service.repository.mark_asset_failed(
            asset_id,
            UUID(organization_id),
            AssetErrorCode.STORAGE_UNAVAILABLE,
            "safe failure",
            NOW + timedelta(seconds=1),
        )
    return asset


def ready_asset(client, app):
    organization_id, project_id, session_response = create_hierarchy(client)
    session = session_response.json()
    asset = persist_asset(app, organization_id, project_id, session["session_id"], terminal="ready")
    url = f"/sessions/{session['session_id']}/assets/{asset.asset_id}/access"
    return organization_id, project_id, session, asset, url


def test_ready_asset_access_defaults_to_five_minutes_and_is_not_persisted(
    client, app, asset_access_signer
):
    organization_id, _, session, asset, url = ready_asset(client, app)
    before = app.state.service.repository.get_asset(
        UUID(session["session_id"]), asset.asset_id, UUID(organization_id)
    )

    response = client.post(url, headers={"X-Organization-ID": organization_id}, json={})

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0.0",
        "asset_id": str(asset.asset_id),
        "method": "GET",
        "url": asset_access_signer.url,
        "expires_at": (NOW + timedelta(seconds=300)).isoformat().replace("+00:00", "Z"),
        "content_type": "image/png",
    }
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert asset_access_signer.calls == [(asset.object_key, NOW + timedelta(seconds=300))]
    after = app.state.service.repository.get_asset(
        UUID(session["session_id"]), asset.asset_id, UUID(organization_id)
    )
    assert after == before
    assert (
        len(
            app.state.service.repository.list_assets(
                UUID(session["session_id"]), UUID(organization_id)
            )
        )
        == 1
    )
    assert "signed_url" not in AssetRow.__table__.columns
    metadata = client.get(
        url.removesuffix("/access"), headers={"X-Organization-ID": organization_id}
    )
    assert {"url", "object_key", "bucket"}.isdisjoint(metadata.json())


@pytest.mark.parametrize("ttl", [1, 60, 900])
def test_asset_access_accepts_bounded_strict_ttl(client, app, asset_access_signer, ttl):
    organization_id, _, _, _, url = ready_asset(client, app)
    response = client.post(
        url, headers={"X-Organization-ID": organization_id}, json={"ttl_seconds": ttl}
    )
    assert response.status_code == 200
    assert asset_access_signer.calls[-1][1] == NOW + timedelta(seconds=ttl)


@pytest.mark.parametrize("ttl", [0, -1, 901, True, "300", 1.5])
def test_asset_access_rejects_invalid_ttl_before_signing(client, app, asset_access_signer, ttl):
    organization_id, _, _, _, url = ready_asset(client, app)
    response = client.post(
        url, headers={"X-Organization-ID": organization_id}, json={"ttl_seconds": ttl}
    )
    assert response.status_code == 422
    assert asset_access_signer.calls == []


def test_asset_access_rejects_extra_request_fields(client, app, asset_access_signer):
    organization_id, _, _, _, url = ready_asset(client, app)
    response = client.post(
        url,
        headers={"X-Organization-ID": organization_id},
        json={"bucket": "caller-selected"},
    )
    assert response.status_code == 422
    assert asset_access_signer.calls == []


def test_asset_access_requires_bearer_not_tenant_header(client, app, asset_access_signer):
    organization_id, _, _, _, url = ready_asset(client, app)
    response = client.post(
        url,
        headers={"Authorization": "", "X-Organization-ID": organization_id},
        json={},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert asset_access_signer.calls == []


def test_member_access_and_membership_revocation(client, app, asset_access_signer):
    organization_id, _, _, _, url = ready_asset(client, app)
    member = client.get("/me", headers=auth("test-asset-member")).json()
    client.post(
        f"/organizations/{organization_id}/memberships",
        json={"principal_id": member["principal_id"], "role": "member"},
    )
    member_headers = {"X-Organization-ID": organization_id, **auth("test-asset-member")}
    assert client.post(url, headers=member_headers, json={}).status_code == 200
    calls = len(asset_access_signer.calls)

    removed = client.delete(
        f"/organizations/{organization_id}/memberships/{member['principal_id']}"
    )
    assert removed.status_code == 204
    denied = client.post(url, headers=member_headers, json={})
    assert denied.status_code == 404
    assert len(asset_access_signer.calls) == calls


@pytest.mark.parametrize("role", ["admin", "member"])
def test_all_non_owner_membership_roles_can_request_asset_access(
    client, app, asset_access_signer, role
):
    organization_id, _, _, _, url = ready_asset(client, app)
    principal = client.get("/me", headers=auth(f"test-{role}-viewer")).json()
    created = client.post(
        f"/organizations/{organization_id}/memberships",
        json={"principal_id": principal["principal_id"], "role": role},
    )
    assert created.status_code == 201
    response = client.post(
        url,
        headers={
            "X-Organization-ID": organization_id,
            **auth(f"test-{role}-viewer"),
        },
        json={},
    )
    assert response.status_code == 200
    assert len(asset_access_signer.calls) == 1


def test_non_member_and_foreign_organization_cannot_reach_signer(client, app, asset_access_signer):
    organization_id, _, _, _, url = ready_asset(client, app)
    denied = client.post(
        url,
        headers={"X-Organization-ID": organization_id, **auth("test-non-member")},
        json={},
    )
    assert denied.status_code == 404

    foreign = client.post(
        "/organizations", headers=auth("test-foreign-owner"), json={"name": "Foreign"}
    ).json()
    wrong_tenant = client.post(
        url,
        headers={"X-Organization-ID": foreign["organization_id"], **auth("test-foreign-owner")},
        json={},
    )
    assert wrong_tenant.status_code == 404
    assert asset_access_signer.calls == []


def test_cross_session_asset_cannot_reach_signer(client, app, asset_access_signer):
    organization_id, project_id, _, asset, _ = ready_asset(client, app)
    other = client.post(
        f"/projects/{project_id}/sessions",
        headers={"X-Organization-ID": organization_id},
        json={"role_id": "retail_client", "locale": "en"},
    ).json()
    response = client.post(
        f"/sessions/{other['session_id']}/assets/{asset.asset_id}/access",
        headers={"X-Organization-ID": organization_id},
        json={},
    )
    assert response.status_code == 404
    assert asset_access_signer.calls == []


@pytest.mark.parametrize("terminal", ["pending", "failed"])
def test_non_ready_asset_is_rejected_without_signing(client, app, asset_access_signer, terminal):
    organization_id, project_id, session_response = create_hierarchy(client)
    session = session_response.json()
    asset = persist_asset(
        app, organization_id, project_id, session["session_id"], terminal=terminal
    )
    response = client.post(
        f"/sessions/{session['session_id']}/assets/{asset.asset_id}/access",
        headers={"X-Organization-ID": organization_id},
        json={},
    )
    assert response.status_code == 409
    assert response.json() == {
        "error": "asset_not_ready",
        "detail": "Asset is not ready for temporary read access",
    }
    assert asset_access_signer.calls == []


def test_signer_failure_is_safely_redacted(client, app, asset_access_signer):
    organization_id, _, _, asset, url = ready_asset(client, app)
    asset_access_signer.error = f"credential failed for {asset.object_key} with signed-url-secret"
    response = client.post(url, headers={"X-Organization-ID": organization_id}, json={})
    assert response.status_code == 503
    assert response.json() == {
        "error": "asset_access_unavailable",
        "detail": "Temporary asset read access is unavailable",
    }
    serialized = response.text
    assert asset.object_key not in serialized
    assert "credential" not in serialized
    assert "signed-url-secret" not in serialized


@pytest.mark.parametrize("invalid_url", ["http://assets.test/a", "/relative", "https://bad url"])
def test_invalid_signer_output_is_unavailable(client, app, asset_access_signer, invalid_url):
    organization_id, _, _, _, url = ready_asset(client, app)
    asset_access_signer.url = invalid_url
    response = client.post(url, headers={"X-Organization-ID": organization_id}, json={})
    assert response.status_code == 503
    assert response.json()["error"] == "asset_access_unavailable"
    assert invalid_url not in response.text


def test_asset_access_openapi_is_post_only_and_secured(client):
    document = client.app.openapi()
    path = document["paths"]["/sessions/{session_id}/assets/{asset_id}/access"]
    assert set(path) == {"post"}
    operation = path["post"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert operation["requestBody"]["required"] is True
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "SignedAssetReadAccess"
    )
    assert "security" not in document["paths"]["/health"]["get"]


def test_production_composition_builds_gcs_signer_without_gcp_network(
    monkeypatch, engine, asset_access_signer, generation_task_publisher
):
    captured = []

    def fake_constructor(config):
        captured.append(config)
        return asset_access_signer

    monkeypatch.setattr("jewelai_api.app.GcsPrivateObjectAccessSigner", fake_constructor)
    settings = RuntimeSettings(
        database_url="sqlite+pysqlite://",
        repository_root=Path(__file__).resolve().parents[3],
        asset_signing=GcsAssetStorageConfig(
            bucket_name="jewelai-assets-prod",
            project_id="jewelai-prod",
            signing_service_account_email=("signer@jewelai-prod.iam.gserviceaccount.com"),
        ),
    )
    application = create_app(
        settings,
        engine=engine,
        clock=lambda: NOW,
        token_verifier=FakeTokenVerifier(),
        generation_task_publisher=generation_task_publisher,
    )
    assert application.state.service._asset_access_signer is asset_access_signer
    assert captured == [settings.asset_signing]


def test_app_factory_requires_gcs_configuration_without_injected_signer(engine):
    with pytest.raises(ValueError, match="GCS Asset signing configuration"):
        create_app(
            RuntimeSettings(
                database_url="sqlite+pysqlite://",
                repository_root=Path(__file__).resolve().parents[3],
            ),
            engine=engine,
            token_verifier=FakeTokenVerifier(),
        )
