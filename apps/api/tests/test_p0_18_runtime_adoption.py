import json
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from conftest import NOW, ROOT, create_hierarchy
from jewelai_assets import (
    Asset,
    AssetContentType,
    AssetKind,
    AssetStatus,
    build_object_key,
)
from jewelai_domain.models import Design, MessageSource
from jewelai_domain.models_v1_1 import (
    DesignRevisionV1_1,
    migrate_design_revision_v1_to_v1_1,
    upgrade_design_revision_v1_to_v1_1,
)
from jewelai_domain.revisions import confirm_field, lock_field, revise_design
from jewelai_persistence import (
    Base,
    DuplicateRevisionError,
    NotFoundError,
    OwnershipMismatchError,
    StaleRevisionError,
    create_database_engine,
)
from test_api import create_ready_prompt
from test_persistence import build_service, create_persisted_session


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


@pytest.fixture(params=("sqlite", pytest.param("postgres", marks=pytest.mark.postgres)))
def migration_context(request, engine):
    """Use only the disposable SQLite/CI PostgreSQL test databases."""
    if request.param == "postgres":
        database_url = os.getenv("TEST_POSTGRES_URL")
        if not database_url:
            pytest.skip("TEST_POSTGRES_URL is required for migration transaction coverage")
        engine = create_database_engine(database_url)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    try:
        service = build_service(engine)
        organization, _, session = create_persisted_session(service)
        repository = service.repository
        current = repository.get_current_revision(session.session_id, organization.organization_id)

        payload = json.loads(
            (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
        )["design"]

        def unconfirm(value):
            if isinstance(value, dict):
                if value.get("availability") == "value":
                    value.update(confirmed=False, locked=False)
                for child in value.values():
                    unconfirm(child)
            elif isinstance(value, list):
                for child in value:
                    unconfirm(child)

        unconfirm(payload)
        payload["center_stone"]["weight"] = {
            "availability": "value",
            "origin": "derived",
            "value": {"value": 3.0, "unit": "ct"},
            "sources": [
                {
                    "kind": "knowledge",
                    "record_id": "synthetic-weight",
                    "version": "1.0.0",
                    "recorded_at": NOW.isoformat(),
                }
            ],
            "uncertainty": "Synthetic historical estimate, not a measurement",
        }
        payload["construction"]["gallery"] = {
            "availability": "value",
            "origin": "assumed",
            "value": "open",
            "source": {
                "kind": "rule",
                "rule_id": "synthetic-gallery",
                "version": "1.0.0",
                "recorded_at": NOW.isoformat(),
            },
            "rationale": "Explicitly recorded historical assumption",
        }
        payload["construction"]["clasp"] = {
            "availability": "not_applicable",
            "reason": "Ring has no clasp",
            "source": current.event.source.model_dump(mode="json"),
        }
        proposed = revise_design(
            current,
            Design.model_validate(payload),
            expected_revision_id=current.revision_id,
            source=current.event.source,
            reason="Persist rich synthetic historical state",
            created_at=NOW,
        )
        repository.append_revision_cas(
            session.session_id, organization.organization_id, current.revision_id, proposed
        )
        current = proposed
        for transition in (confirm_field, lock_field):
            proposed = transition(
                current,
                "center_stone.shape",
                expected_revision_id=current.revision_id,
                source=current.event.source,
                reason="Confirm and protect historical oval shape",
                created_at=NOW,
            )
            repository.append_revision_cas(
                session.session_id, organization.organization_id, current.revision_id, proposed
            )
            current = proposed
        migrated = migrate_design_revision_v1_to_v1_1(
            current,
            revision_id=uuid4(),
            created_at=NOW + timedelta(hours=1),
            source=MessageSource(message_id="explicit-schema-upgrade", recorded_at=NOW),
            reason="Explicit additive schema migration",
        )
        yield service, session.session_id, organization.organization_id, current, migrated
    finally:
        if request.param == "postgres":
            Base.metadata.drop_all(engine)
            engine.dispose()


def test_canonical_migration_preserves_rich_historical_state(migration_context):
    service, session_id, organization_id, current, migrated = migration_context
    repository = service.repository
    history = repository.list_revisions(session_id, organization_id)

    assert current.design.center_stone.shape.value == "oval"
    assert current.design.center_stone.shape.confirmed
    assert current.design.center_stone.shape.locked
    assert current.design.center_stone.weight.origin == "derived"
    assert current.design.construction.gallery.origin == "assumed"
    assert current.design.center_stone.dimensions.availability == "unknown"
    assert current.design.construction.clasp.availability == "not_applicable"
    persisted = repository.upgrade_design_session_schema_v1_1(
        session_id, organization_id, current.revision_id, migrated
    )

    assert persisted == repository.get_current_revision(session_id, organization_id) == migrated
    assert persisted.design == upgrade_design_revision_v1_to_v1_1(current).design
    assert persisted.design.center_stone.material_origin_status is None
    assert persisted.design.halo.enabled is None
    assert persisted.design.metal.components is None
    assert persisted.event == migrated.event
    assert persisted.created_at == NOW + timedelta(hours=1)
    assert persisted.parent_revision_id == current.revision_id
    assert persisted.design_id == current.design_id
    assert persisted.revision == current.revision + 1
    assert repository.list_revisions(session_id, organization_id) == (*history, migrated)
    session = repository.get_design_session(session_id, organization_id)
    assert session.design_schema_version == "1.1.0"
    assert session.current_revision_id == migrated.revision_id


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        pytest.param(("center_stone", "shape", "value"), "round", id="locked-value"),
        pytest.param(("metal", "material", "value"), "platinum", id="unlocked-value"),
        pytest.param(("metal", "material", "confirmed"), True, id="confirmation"),
        pytest.param(("center_stone", "shape", "locked"), False, id="unlock"),
        pytest.param(("metal", "material", "source", "message_id"), "forged", id="source"),
        pytest.param(
            ("center_stone", "weight", "sources", 0, "record_id"), "forged", id="derived-source"
        ),
        pytest.param(("center_stone", "weight", "uncertainty"), "certain", id="uncertainty"),
        pytest.param(
            ("construction", "gallery", "source", "rule_id"), "forged", id="assumed-source"
        ),
        pytest.param(("construction", "gallery", "rationale"), "forged", id="rationale"),
        pytest.param(
            ("center_stone", "dimensions", "requirement"), "required", id="unknown-metadata"
        ),
        pytest.param(("construction", "clasp", "reason"), "forged", id="not-applicable"),
        pytest.param(("metal", "material"), None, id="reset-to-none"),
        pytest.param(("metal", "material"), {"availability": "unknown"}, id="reset-to-unknown"),
        pytest.param(("side_stones", 0, "group_id"), "replacement", id="stable-group-id"),
        pytest.param(("side_stones", 0, "stones", "shape", "value"), "round", id="group-value"),
        pytest.param(("side_stones",), [], id="remove-group"),
        pytest.param(
            ("visual_constraints", "value", 0, "instruction"), "Different view", id="constraint"
        ),
        pytest.param(("references", "value", 0, "note"), "Different reference", id="reference"),
    ],
)
def test_schema_migration_rejects_state_changes_atomically(migration_context, path, replacement):
    service, session_id, organization_id, current, migrated = migration_context
    repository = service.repository
    payload = migrated.model_dump(mode="json")
    cursor = payload["design"]
    for segment in path[:-1]:
        cursor = cursor[segment]
    cursor[path[-1]] = replacement
    candidate = DesignRevisionV1_1.model_validate(payload)
    assert_rejected_migration_is_atomic(repository, session_id, organization_id, current, candidate)


def assert_rejected_migration_is_atomic(
    repository, session_id, organization_id, current, candidate
):
    history = repository.list_revisions(session_id, organization_id)
    before = repository.get_design_session(session_id, organization_id)
    with pytest.raises(DuplicateRevisionError, match="canonical"):
        repository.upgrade_design_session_schema_v1_1(
            session_id, organization_id, current.revision_id, candidate
        )
    assert repository.get_current_revision(session_id, organization_id) == current
    assert repository.list_revisions(session_id, organization_id) == history
    after = repository.get_design_session(session_id, organization_id)
    assert after.current_revision_id == before.current_revision_id == current.revision_id
    assert after.design_schema_version == before.design_schema_version == "1.0.0"
    assert after.updated_at == before.updated_at
    with pytest.raises(NotFoundError):
        repository.get_revision(session_id, candidate.revision_id, organization_id)


def test_schema_migration_rejects_injected_additive_value(migration_context):
    service, session_id, organization_id, current, migrated = migration_context
    repository = service.repository
    payload = migrated.model_dump(mode="json")
    payload["design"]["center_stone"]["material_origin_status"] = {
        "availability": "value",
        "origin": "explicit",
        "value": "natural",
        "source": migrated.event.source.model_dump(mode="json"),
        "confirmed": True,
    }
    assert_rejected_migration_is_atomic(
        repository, session_id, organization_id, current, DesignRevisionV1_1.model_validate(payload)
    )


@pytest.mark.parametrize("action", ("confirm", "lock", "unlock"))
def test_schema_migration_requires_existing_canonical_edit_event(migration_context, action):
    service, session_id, organization_id, current, migrated = migration_context
    repository = service.repository
    payload = migrated.model_dump(mode="json")
    payload["event"]["action"] = action
    assert_rejected_migration_is_atomic(
        repository, session_id, organization_id, current, DesignRevisionV1_1.model_validate(payload)
    )


def test_schema_migration_rejects_stale_and_repeated_writes(migration_context):
    service, session_id, organization_id, current, migrated = migration_context
    repository = service.repository
    child = confirm_field(
        current,
        "metal.material",
        expected_revision_id=current.revision_id,
        source=current.event.source,
        reason="Legitimate intervening confirmation",
        created_at=NOW,
    )
    repository.append_revision_cas(session_id, organization_id, current.revision_id, child)
    with pytest.raises(StaleRevisionError):
        repository.upgrade_design_session_schema_v1_1(
            session_id, organization_id, current.revision_id, migrated
        )
    canonical = migrate_design_revision_v1_to_v1_1(
        child,
        revision_id=migrated.revision_id,
        created_at=migrated.created_at,
        source=migrated.event.source,
        reason=migrated.event.reason,
    )
    repository.upgrade_design_session_schema_v1_1(
        session_id, organization_id, child.revision_id, canonical
    )
    with pytest.raises(StaleRevisionError):
        repository.upgrade_design_session_schema_v1_1(
            session_id, organization_id, child.revision_id, canonical
        )
    assert repository.get_current_revision(session_id, organization_id) == canonical


def test_schema_migration_rejects_foreign_organization_and_parent(migration_context):
    service, session_id, organization_id, current, migrated = migration_context
    repository = service.repository
    foreign_organization, _, foreign_session = create_persisted_session(service)
    foreign_organization_id = foreign_organization.organization_id
    with pytest.raises(OwnershipMismatchError):
        repository.upgrade_design_session_schema_v1_1(
            session_id, foreign_organization_id, current.revision_id, migrated
        )
    with pytest.raises(OwnershipMismatchError):
        repository.get_revision(session_id, current.revision_id, foreign_organization_id)
    # Even a valid parent from another session must not replace this session's parent.
    with pytest.raises(OwnershipMismatchError):
        repository.upgrade_design_session_schema_v1_1(
            foreign_session.session_id, organization_id, current.revision_id, migrated
        )
    foreign_current = repository.get_current_revision(
        foreign_session.session_id, foreign_organization_id
    )
    # A real foreign revision cannot serve as the expected parent, even with
    # a candidate that names that revision and otherwise validates as v1.1.
    foreign_candidate = migrate_design_revision_v1_to_v1_1(
        foreign_current,
        revision_id=uuid4(),
        created_at=NOW,
        source=foreign_current.event.source,
        reason="Synthetic foreign parent",
    )
    with pytest.raises(StaleRevisionError):
        repository.upgrade_design_session_schema_v1_1(
            session_id, organization_id, foreign_current.revision_id, foreign_candidate
        )
    assert (
        repository.get_current_revision(foreign_session.session_id, foreign_organization_id)
        == foreign_current
    )
    assert repository.get_current_revision(session_id, organization_id) == current
    assert (
        repository.get_design_session(session_id, organization_id).design_schema_version == "1.0.0"
    )
