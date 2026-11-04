"""PCAP real session orchestration; synthetic READY facts, no provider/paid calls."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from jewelai_domain.lock_protection import state_fields
from jewelai_domain.models import MessageSource, Unknown
from jewelai_domain.models_v1_1 import DesignV1_1, migrate_design_revision_v1_to_v1_1
from jewelai_domain.revisions import confirm_field, lock_field, revise_design
from jewelai_domain.rules import ReadyDecision
from jewelai_persistence import NotFoundError
from jewelai_prompts import GenerationPreparationError, build_internal_final_prompt_handoff
from jewelai_prompts.revision_projection import project_revision
from test_keep_atomicity import _record, _snapshot
from test_persistence import NOW, build_service, create_persisted_session
from test_prompt_enrichment_runtime import _request, _runtime

from jewelai_api.prompt_enrichment_runtime import (
    PersistedUserCorrectionRequest,
    PromptEnrichmentRuntimeError,
    PromptEnrichmentRuntimeService,
    build_final_prompt_snapshot,
)

ROOT = Path(__file__).resolve().parents[3]


def capacity_session(engine, tmp_path, count, decoration, locale, rich=False):
    service = build_service(engine)
    organization, project, session = create_persisted_session(service)
    if locale == "ru":
        from jewelai_api.schemas import CreateSessionRequest

        session = service.create_session(
            project.project_id,
            organization.organization_id,
            CreateSessionRequest(role_id="retail_client", locale="ru-RU"),
        )
    repository = service.repository
    current = repository.get_current_revision(session.session_id, organization.organization_id)
    source = MessageSource(message_id="capacity-audit", recorded_at=NOW)
    migrated = migrate_design_revision_v1_to_v1_1(
        current,
        revision_id=uuid4(),
        created_at=NOW,
        source=source,
        reason="Synthetic additive-schema capacity test",
    )
    repository.upgrade_design_session_schema_v1_1(
        session.session_id, organization.organization_id, current.revision_id, migrated
    )
    data = json.loads((ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text())[
        "design"
    ]
    data["references"]["value"] = []

    def explicit(value):
        return dict(
            availability="value",
            origin="explicit",
            value=value,
            source=migrated.event.source.model_dump(mode="json"),
            confirmed=False,
            locked=False,
        )

    data["metal"]["components"] = explicit(
        [
            {"component_id": key, "material": explicit(material)}
            for key, material in [("z_head", "platinum"), ("a_shank", "gold"), ("gallery", "gold")][
                :count
            ]
        ]
    )
    if decoration:
        data["decorative_elements"] = explicit(
            [{"element_id": "filigree", "motif": explicit("floral")}]
        )
    if rich:
        component = data["metal"]["components"]["value"][1]
        component.update(
            color=explicit("white"),
            purity=data["metal"]["purity"],
            finish=explicit("matte"),
            coating=explicit({"material": explicit("rhodium")}),
        )
        data["composition"] = explicit(
            {"symmetry_mode": explicit("symmetrical"), "rhythm": explicit("regular")}
        )
    # Reuse exact synthetic READY prerequisites from test_effective_readiness;
    # these numbers are not factual gemstone-dimension recommendations.
    data["center_stone"]["setting"] = explicit("prong_setting")
    data["center_stone"]["dimensions"] = explicit(
        {
            "length": {"value": 9.1, "unit": "mm"},
            "width": {"value": 7.2, "unit": "mm"},
            "depth": {"value": 4.8, "unit": "mm"},
        }
    )

    def clear_authority(item):
        if isinstance(item, dict):
            if "availability" in item:
                item.update(confirmed=False, locked=False)
            for value in item.values():
                clear_authority(value)
        elif isinstance(item, list):
            for value in item:
                clear_authority(value)

    clear_authority(data)
    current = revise_design(
        migrated,
        DesignV1_1.model_validate(data),
        expected_revision_id=migrated.revision_id,
        source=source,
        reason="Synthetic professional Product State",
        created_at=NOW,
    )
    repository.append_revision_cas(
        session.session_id, organization.organization_id, migrated.revision_id, current
    )
    paths = [
        p
        for p, s in state_fields(current.design).items()
        if s is not None and not isinstance(s, Unknown)
    ]
    for path in sorted(paths, key=len, reverse=True):
        previous = current
        current = confirm_field(
            current,
            ".".join(path),
            expected_revision_id=current.revision_id,
            source=source,
            reason="Synthetic explicit confirmation",
            created_at=NOW,
        )
        repository.append_revision_cas(
            session.session_id, organization.organization_id, previous.revision_id, current
        )
    for path in ("metal.color", "metal.components.z_head.material"):
        previous = current
        current = lock_field(
            current,
            path,
            expected_revision_id=current.revision_id,
            source=source,
            reason="Synthetic explicit lock",
            created_at=NOW,
        )
        repository.append_revision_cas(
            session.session_id, organization.organization_id, previous.revision_id, current
        )
    runtime, store, active, report = _runtime(service, tmp_path)
    text = (
        "Create an oval white-gold ring."
        if locale == "en"
        else "Хочу овальное кольцо из белого золота."
    )
    request = _request(service, organization, session, text)
    return service, organization, session, current, runtime, store, active, report, request


@pytest.mark.parametrize(
    "count,decoration,rich",
    [
        (2, False, False),
        (3, False, False),
        (2, True, False),
        (3, True, False),
        (2, True, True),
        (3, True, True),
    ],
)
@pytest.mark.parametrize("locale", ["en", "ru"])
def test_ready_session_preserves_complete_state_and_retries_without_new_cycles(
    engine, tmp_path, count, decoration, rich, locale
):
    service, org, session, revision, runtime, store, active, report, request = capacity_session(
        engine, tmp_path, count, decoration, locale, rich
    )
    before = revision.model_dump_json()
    result = runtime.start_initial_message(request)
    snapshot = build_final_prompt_snapshot(
        service.repository,
        session_id=session.session_id,
        organization_id=org.organization_id,
        artifacts=service.artifacts,
        artifact_store=store,
        active_release=active,
        validation_report=report,
    )
    assert isinstance(snapshot.rule_decision, ReadyDecision)
    assert snapshot.enrichment_result.enrichment_version == "1.3.0"
    prompt = result.workflow.final_output.internal_final_prompt
    assert prompt.schema_version == "2.1.0"
    assert prompt.readiness.value == "ready_with_unresolved"
    if (count == 3 and decoration) or rich:
        assert 20_000 < len(prompt.prompt_text) <= 32_000
    assert len(prompt.prompt_text.encode("utf-8")) <= 128_000
    expected = project_revision(revision)
    assert {f.target: (f.value, f.origin, f.confirmed, f.locked) for f in prompt.design_facts} == {
        e.concrete_target: (e.value, e.origin, e.confirmed, e.locked)
        for e in expected.specification_entries
    }
    assert prompt.disclosures == expected.disclosures
    assert (
        service.repository.get_current_revision(
            session.session_id, org.organization_id
        ).model_dump_json()
        == before
    )
    assert any(
        f.target == "metal.components.z_head.material" and f.locked for f in prompt.design_facts
    )
    if decoration:
        assert any(f.target == "decorative_elements.filigree.motif" for f in prompt.design_facts)
    source = build_internal_final_prompt_handoff(result.workflow.final_output)
    restarted = PromptEnrichmentRuntimeService(
        service.repository,
        service.artifacts,
        store,
        knowledge_package_id=runtime.knowledge_package_id,
        knowledge_artifact_version=runtime.knowledge_artifact_version,
        active_release=active,
        validation_report=report,
        clock=lambda: NOW,
        uuid_factory=uuid4,
    )
    for _ in range(2):
        assert (
            restarted.build_current_internal_final_prompt_handoff(
                session.session_id, org.organization_id
            )
            == source
        )
    assert (
        len(service.repository.list_enrichment_cycles(session.session_id, org.organization_id)) == 1
    )


def test_overflow_retains_valid_earlier_commits_and_read_retries_are_nonmutating(
    engine, tmp_path, monkeypatch
):
    import jewelai_prompts.downstream_preparation as module

    service, org, session, revision, runtime, *_rest, request = capacity_session(
        engine, tmp_path, 3, True, "en"
    )
    # Establish an actually committed cycle and pin before injecting overflow.
    accepted = runtime.start_initial_message(request)
    original_handoff = build_internal_final_prompt_handoff(accepted.workflow.final_output)
    repository = service.repository
    cycles = repository.list_enrichment_cycles(session.session_id, org.organization_id)
    assert len(cycles) == 1
    pin = repository.get_knowledge_release_pin(session.session_id, org.organization_id)
    assert cycles[0].release_pin == pin
    correction = _request(service, org, session, "Make the design minimalist.")
    before = _snapshot(engine, session.session_id)  # Message already persisted separately.
    with monkeypatch.context() as failure:
        failure.setattr(module, "IFP_V2_1_MAX_BYTES", 1)  # Injected fault, not qualification.
        with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
            runtime.apply_persisted_user_correction(
                org.organization_id,
                PersistedUserCorrectionRequest(
                    session_id=session.session_id,
                    expected_revision_id=revision.revision_id,
                    message_id=correction.message_id,
                ),
            )
        assert _snapshot(engine, session.session_id) == before
        for _ in range(2):
            with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
                runtime.build_current_internal_final_prompt_handoff(
                    session.session_id, org.organization_id
                )
            assert _snapshot(engine, session.session_id) == before
        with pytest.raises(PromptEnrichmentRuntimeError):
            runtime.start_initial_message(request)  # Real first-cycle conflict, no duplicate.
    assert _snapshot(engine, session.session_id) == before
    assert repository.list_enrichment_cycles(session.session_id, org.organization_id) == cycles
    assert repository.get_knowledge_release_pin(session.session_id, org.organization_id) == pin
    assert repository.get_current_revision(session.session_id, org.organization_id) == revision
    # Once the injected limit is removed, readback returns the exact original handoff.
    assert (
        runtime.build_current_internal_final_prompt_handoff(session.session_id, org.organization_id)
        == original_handoff
    )
    assert _snapshot(engine, session.session_id) == before
    _record(
        "capacity-prior-commit",
        dict(
            before=before,
            after=_snapshot(engine, session.session_id),
            committed_cycle_count=len(cycles),
            pin={
                key: getattr(pin, key)
                for key in (
                    "package_id",
                    "artifact_version",
                    "runtime_sha256",
                    "validation_report_sha256",
                )
            },
            handoff_hash=original_handoff.content_hash,
            failed_correction_rolled_back=True,
            read_failures=2,
            restored_handoff_identical=True,
        ),
    )


def test_initial_capacity_failure_rolls_back_cycle_pin_and_is_retryable(
    engine, tmp_path, monkeypatch
):
    import jewelai_prompts.downstream_preparation as module

    service, org, session, revision, runtime, *_rest, request = capacity_session(
        engine, tmp_path, 3, True, "en"
    )
    repository = service.repository
    before = _snapshot(engine, session.session_id)
    assert before["enrichment_cycle"] == []
    with pytest.raises(NotFoundError, match="no verified Knowledge release pin"):
        repository.get_knowledge_release_pin(session.session_id, org.organization_id)
    with monkeypatch.context() as failure:
        failure.setattr(module, "IFP_V2_1_MAX_BYTES", 1)
        for _ in range(2):
            with pytest.raises(GenerationPreparationError, match="preparation_capacity_exceeded"):
                runtime.start_initial_message(request)
            assert _snapshot(engine, session.session_id) == before
            with pytest.raises(NotFoundError, match="no verified Knowledge release pin"):
                repository.get_knowledge_release_pin(session.session_id, org.organization_id)
    assert repository.get_current_revision(session.session_id, org.organization_id) == revision
    # Failure did not consume the Message or first-cycle slot.
    result = runtime.start_initial_message(request)
    cycles = repository.list_enrichment_cycles(session.session_id, org.organization_id)
    assert len(cycles) == 1
    assert result.workflow.enrichment_cycle_id == cycles[0].enrichment_cycle_id
    assert cycles[0].release_pin == repository.get_knowledge_release_pin(
        session.session_id, org.organization_id
    )
    _record(
        "capacity-initial-rollback",
        dict(
            before=before,
            failed_attempts=2,
            failed_attempts_unchanged=True,
            initial_pin_absent=True,
            successful_retry_cycle_count=len(cycles),
            pin={
                key: getattr(cycles[0].release_pin, key)
                for key in (
                    "package_id",
                    "artifact_version",
                    "runtime_sha256",
                    "validation_report_sha256",
                )
            },
            after_success=_snapshot(engine, session.session_id),
        ),
    )
