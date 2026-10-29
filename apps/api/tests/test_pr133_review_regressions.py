"""PR #133 R1/R2: actual HTTP regressions, synthetic releases, no provider calls."""

import json
from uuid import UUID, uuid4

import pytest
from conftest import NOW
from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import DesignV1_1, migrate_design_revision_v1_to_v1_1
from jewelai_domain.revisions import confirm_field, lock_field, revise_design
from jewelai_persistence import Base
from jewelai_persistence.models import GenerationPreparationRow, KnowledgeReleaseBindingRow
from jewelai_prompts import GenerationPreparation
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from test_effective_readiness import ready_session as ready_session
from test_generation_preparations import counts, expected, post
from test_persistence import build_service
from test_prompt_enrichment_http import _message


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(value)
    try:
        yield value
    finally:
        value.dispose()


def assert_preparation_roundtrip(ctx, engine):
    request, key = expected(ctx), uuid4()
    before = ctx.service.repository.list_enrichment_cycles(UUID(ctx.sid), UUID(ctx.org))
    with engine.connect() as db:
        binding = db.scalar(select(KnowledgeReleaseBindingRow.payload))
    created = post(ctx, request, key)
    assert created.status_code == 201, created.json()
    identity = created.json()
    after_post = counts(engine)
    read = ctx.client.get(
        f"/sessions/{ctx.sid}/generation-preparations/{identity['preparation_id']}",
        headers=ctx.headers,
    )
    replay = post(ctx, request, key)
    evidence = dict(
        post=created.status_code, rows=after_post, get=read.status_code, replay=replay.status_code
    )
    assert evidence == dict(post=201, rows=(1, 1, 0, 0), get=200, replay=200)
    assert read.json() == replay.json() == identity
    assert counts(engine) == (1, 1, 0, 0)
    with engine.connect() as db:
        raw = db.scalar(select(GenerationPreparationRow.artifact_bytes))
        assert db.scalar(select(KnowledgeReleaseBindingRow.payload)) == binding
    artifact = GenerationPreparation(raw)
    assert artifact.canonical == raw
    assert artifact.payload.artifact_hash == identity["artifact_hash"]
    assert artifact.payload.source_handoff_hash == request["expected_handoff_hash"]
    assert (
        artifact.payload.source_handoff.knowledge_release.runtime_sha256
        == binding["runtime_sha256"]
    )
    assert ctx.service.repository.list_enrichment_cycles(UUID(ctx.sid), UUID(ctx.org)) == before
    assert ctx.provider.calls == []


def test_staticpool_preparation_post_get_replay_are_durable(ready_session, engine):
    assert_preparation_roundtrip(ready_session(), engine)


def test_v1_1_only_policy_survives_full_http_lifecycle(engine, tmp_path, monkeypatch):
    import test_prompt_enrichment_composition as composition

    policy_id = "POL-REVIEW-R2-COMPOSITION"
    payload = json.loads(composition.KNOWLEDGE.read_text(encoding="utf-8"))
    payload["sources"].append(
        dict(
            source_id="DEC-REVIEW-R2",
            title="Synthetic integration test only",
            source_type="INTERNAL_DECISION",
            language="not_applicable",
            evidence_tier="INTERNAL",
            lifecycle_status="REVIEWED",
        )
    )
    payload["policies"].append(
        dict(
            policy_id=policy_id,
            target="composition.symmetry_mode",
            effect="Preserve explicit symmetry state in the synthetic test.",
            source_kind="INTERNAL_PRODUCT_DECISION",
            source_refs=["DEC-REVIEW-R2"],
            lifecycle_status="REVIEWED",
        )
    )
    original_release, original_hierarchy = composition._release, composition.create_hierarchy
    seeded = {}

    def release(path, version="1.0.0"):
        return original_release(path, version, bundle=payload)

    def hierarchy(client, *args, **kwargs):
        org, project, response = original_hierarchy(client, *args, **kwargs)
        service = build_service(engine)
        repository = service.repository
        sid, oid = UUID(response.json()["session_id"]), UUID(org)
        message = _message(client, str(sid), org, "Explicit synthetic composition and component")
        source = MessageSource(message_id=message["message_id"], recorded_at=NOW)
        current = repository.get_current_revision(sid, oid)
        migrated = migrate_design_revision_v1_to_v1_1(
            current,
            revision_id=uuid4(),
            created_at=NOW,
            source=source,
            reason="Explicit synthetic Schema 1.1 test setup",
        )
        repository.upgrade_design_session_schema_v1_1(sid, oid, current.revision_id, migrated)

        def explicit(value):
            return dict(
                availability="value",
                origin="explicit",
                value=value,
                source=source.model_dump(mode="json"),
                confirmed=False,
                locked=False,
            )

        design = migrated.design.model_dump(mode="json")
        design["composition"] = explicit({"symmetry_mode": explicit("asymmetrical")})
        design["metal"]["components"] = explicit(
            [{"component_id": "review_shank", "material": explicit("gold")}]
        )
        revision = revise_design(
            migrated,
            DesignV1_1.model_validate(design),
            expected_revision_id=migrated.revision_id,
            source=source,
            reason="Explicit synthetic values",
            created_at=NOW,
        )
        repository.append_revision_cas(sid, oid, migrated.revision_id, revision)
        for transition in (confirm_field, lock_field):
            previous = revision
            revision = transition(
                revision,
                "composition.symmetry_mode",
                expected_revision_id=revision.revision_id,
                source=source,
                reason="Explicit synthetic authority",
                created_at=NOW,
            )
            repository.append_revision_cas(sid, oid, previous.revision_id, revision)
        seeded.update(repository=repository, sid=sid, oid=oid, revision=revision)
        refreshed = client.get(f"/sessions/{sid}", headers={"X-Organization-ID": org})
        assert refreshed.status_code == 200
        return org, project, refreshed

    monkeypatch.setattr(composition, "_release", release)
    monkeypatch.setattr(composition, "create_hierarchy", hierarchy)
    composition.test_enabled_composition_qualifies_release_and_runs_restart_safe_full_http_cycle(
        engine,
        tmp_path,
        monkeypatch,
        "en-US",
        "A white or yellow-gold three-stone ring with an oval sapphire and no halo.",
    )
    repository, sid, oid, original = (seeded[k] for k in ("repository", "sid", "oid", "revision"))
    cycles = repository.list_enrichment_cycles(sid, oid)
    assert len(cycles) == 3
    binding = repository.get_knowledge_release_pin(sid, oid).binding
    assert binding.knowledge_contract_version == "1.1.0"
    protected = original.design.composition.value.symmetry_mode
    component = original.design.metal.components
    for cycle in cycles:
        assert cycle.release_pin.binding == binding
        for matrix in (cycle.result.initial_matrix, cycle.result.final_matrix):
            cell = next(c for c in matrix if c.target == "composition.symmetry_mode")
            assert policy_id in cell.applicable_policy_ids
            assert cell.value == "asymmetrical" and cell.confirmed and cell.locked
            assert cell.provenance.value == "USER_CONFIRMED"
            assert str(protected.source.message_id) in cell.source_ids
        revision = repository.get_revision(sid, cycle.specification_revision_id, oid)
        assert revision.design.composition.value.symmetry_mode == protected
        assert revision.design.metal.components == component
    current = repository.get_current_revision(sid, oid)
    assert current.design.composition.value.symmetry_mode == protected
    assert repository.get_revision(sid, original.revision_id, oid) == original
    config, _, _ = original_release(tmp_path / "restore", bundle=payload)
    client, app, provider = composition._client(engine, config)
    with client:
        response = client.get(
            f"/v1/sessions/{sid}/prompt-enrichment/final-output",
            headers={"X-Organization-ID": str(oid)},
        )
        assert response.status_code == 200, response.json()
        prompt = response.json()["internal_final_prompt"]
        fact = next(f for f in prompt["design_facts"] if f["target"] == "composition.symmetry_mode")
        assert prompt["schema_version"] == "2.1.0"
        assert fact["value"] == "asymmetrical" and fact["confirmed"] and fact["locked"]
        assert fact["origin"] == "explicit" and fact["provenance"] == "USER_CONFIRMED"
        assert str(protected.source.message_id) in fact["source_ids"]
        assert any(
            f["target"] == "metal.components.review_shank.material" for f in prompt["design_facts"]
        )
        assert repository.get_knowledge_release_pin(sid, oid).binding == binding
        assert provider.calls == []
