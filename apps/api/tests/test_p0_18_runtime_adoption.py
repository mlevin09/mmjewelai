from uuid import UUID

import pytest
from conftest import NOW, create_hierarchy
from jewelai_assets import (
    Asset,
    AssetContentType,
    AssetKind,
    AssetStatus,
    build_object_key,
)
from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1
from test_api import create_ready_prompt


def add_ready_reference(app, organization_id, project_id, session_id, asset_id):
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
        content_hash="8" * 64,
        byte_size=32,
        created_at=NOW,
    )
    repository = app.state.service.repository
    repository.create_pending_asset(asset)
    repository.mark_asset_ready(asset_id, UUID(organization_id), NOW)
    return asset


def test_reference_binding_api_is_append_only_scoped_and_idempotent(client, app):
    organization_id, project_id, session_response = create_hierarchy(client)
    session = session_response.json()
    asset_id = UUID("18181818-1818-4181-8181-181818181818")
    add_ready_reference(
        app,
        organization_id,
        project_id,
        session["session_id"],
        asset_id,
    )
    headers = {"X-Organization-ID": organization_id}
    url = f"/sessions/{session['session_id']}/reference-bindings"
    payload = {
        "contract_version": "1.0.0",
        "binding_id": "binding-center-shape",
        "asset_id": str(asset_id),
        "reference_role": "base_design",
        "feature_bindings": [
            {
                "feature_path": "center_stone.shape",
                "relation": "KEEP",
                "target": None,
                "raw_user_language": "keep the stone shape",
                "provenance": "user_text",
                "confidence": 1.0,
                "observability": "EXPLICIT",
            }
        ],
        "presentation_bindings": [],
    }

    created = client.post(url, headers=headers, json=payload)
    assert created.status_code == 201
    assert created.json() == payload

    repeated = client.post(url, headers=headers, json=payload)
    assert repeated.status_code == 201
    assert repeated.json() == payload

    listed = client.get(url, headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"bindings": [payload]}

    single = client.get(f"{url}/{payload['binding_id']}", headers=headers)
    assert single.status_code == 200
    assert single.json() == payload

    changed = {
        **payload,
        "feature_bindings": [
            {
                **payload["feature_bindings"][0],
                "relation": "CHANGE",
            }
        ],
    }
    conflict = client.post(url, headers=headers, json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "reference_binding_conflict"

    foreign = client.post("/organizations", json={"name": "Foreign"}).json()
    denied = client.get(
        f"{url}/{payload['binding_id']}",
        headers={"X-Organization-ID": foreign["organization_id"]},
    )
    assert denied.status_code == 404


def test_reference_binding_requires_frozen_observability(client):
    organization_id, _, session_response = create_hierarchy(client)
    session = session_response.json()
    response = client.post(
        f"/sessions/{session['session_id']}/reference-bindings",
        headers={"X-Organization-ID": organization_id},
        json={
            "contract_version": "1.0.0",
            "binding_id": "missing-observability",
            "asset_id": "18181818-1818-4181-8181-181818181818",
            "reference_role": "base_design",
            "feature_bindings": [
                {
                    "feature_path": "center_stone.shape",
                    "relation": "KEEP",
                    "provenance": "user_text",
                }
            ],
            "presentation_bindings": [],
        },
    )
    assert response.status_code == 422


def test_visualization_verification_api_persists_generation_lineage(client):
    organization_id, _, session, edited, prompt = create_ready_prompt(client)
    headers = {"X-Organization-ID": organization_id}
    run_response = client.post(
        f"/sessions/{session['session_id']}/generation-runs",
        headers=headers,
        json={
            "prompt_revision_id": prompt["prompt_revision_id"],
            "profile_id": "test_default",
        },
    )
    assert run_response.status_code == 201
    run = run_response.json()

    url = f"/sessions/{session['session_id']}/visualization-verifications"
    payload = {
        "contract_version": "1.0.0",
        "verification_id": "verification-run-1",
        "subject": {
            "generation_run_id": run["generation_run_id"],
            "asset_id": None,
            "design_revision_id": edited["revision_id"],
            "previous_asset_id": None,
        },
        "overall_status": "UNVERIFIABLE",
        "action": "ASK",
        "checks": [
            {
                "check_id": "observability-1",
                "dimension": "observability_confidence",
                "status": "UNVERIFIABLE",
                "severity": None,
                "feature_path": "construction.gallery",
                "error_ids": [],
                "evidence": ["gallery hidden by camera angle"],
                "confidence": 0.9,
                "note": None,
            }
        ],
        "error_ids": [],
    }

    created = client.post(url, headers=headers, json=payload)
    assert created.status_code == 201
    assert created.json() == payload
    assert client.get(url, headers=headers).json() == {"verifications": [payload]}
    assert client.get(f"{url}/{payload['verification_id']}", headers=headers).json() == payload

    invalid_lineage = {
        **payload,
        "verification_id": "verification-foreign-run",
        "subject": {
            **payload["subject"],
            "generation_run_id": str(UUID(int=999999)),
        },
    }
    denied = client.post(url, headers=headers, json=invalid_lineage)
    assert denied.status_code == 404


def test_persistence_can_atomically_migrate_one_session_to_schema_v1_1(client, app):
    organization_id, _, session_response = create_hierarchy(client)
    session = session_response.json()
    repository = app.state.service.repository
    session_id = UUID(session["session_id"])
    organization_uuid = UUID(organization_id)
    current = repository.get_current_revision(session_id, organization_uuid)

    migrated = migrate_design_revision_v1_to_v1_1(
        current,
        revision_id=UUID("18181818-1818-4181-8181-181818181819"),
        created_at=NOW,
        source=MessageSource(
            message_id="schema-migration-1.1",
            recorded_at=NOW,
        ),
        reason="Explicit P0-18 schema migration test",
    )
    persisted = repository.upgrade_design_session_schema_v1_1(
        session_id,
        organization_uuid,
        current.revision_id,
        migrated,
    )

    assert persisted.schema_version == "1.1.0"
    stored_session = repository.get_design_session(session_id, organization_uuid)
    assert stored_session.design_schema_version == "1.1.0"
    assert stored_session.current_revision_id == migrated.revision_id
    revisions = repository.list_revisions(session_id, organization_uuid)
    assert [item.schema_version for item in revisions] == ["1.0.0", "1.1.0"]
    assert revisions[1].parent_revision_id == revisions[0].revision_id

    with pytest.raises(ValueError, match="parent"):
        repository.upgrade_design_session_schema_v1_1(
            session_id,
            organization_uuid,
            migrated.revision_id,
            migrated,
        )
