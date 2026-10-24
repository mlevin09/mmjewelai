import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from jewelai_domain import compile_knowledge_library, promote_knowledge_runtime
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore
from jewelai_domain.models import MessageSource
from jewelai_persistence import Base, create_database_engine, create_session_factory
from jewelai_persistence.models import ClarificationPlanRow, EnrichmentCycleRow
from sqlalchemy import event, func, select
from test_enrichment_persistence import _report
from test_persistence import NOW, build_service, create_persisted_session, next_revision

from jewelai_api.clarification_answers import ClarificationAnswer, ClarificationDecision
from jewelai_api.correction_enrichment import UserCorrection
from jewelai_api.prompt_enrichment_runtime import (
    InitialEnrichmentRequest,
    PersistedClarificationAnswerRequest,
    PersistedUserCorrectionRequest,
    PromptEnrichmentRuntimeError,
    PromptEnrichmentRuntimeErrorCode,
    PromptEnrichmentRuntimeService,
    build_final_prompt_snapshot,
)

ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"


def _content_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _runtime(service, tmp_path):
    payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    stored = store.publish(payload)
    compiled, _ = compile_knowledge_library(payload)
    report = _report(compiled)
    active = promote_knowledge_runtime(compiled, report)
    runtime = PromptEnrichmentRuntimeService(
        service.repository,
        service.artifacts,
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        clock=lambda: NOW,
        uuid_factory=uuid4,
    )
    return runtime, store, active, report


def _request(service, organization, session, text):
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    message = service.create_message(session.session_id, organization.organization_id, text)
    return InitialEnrichmentRequest(
        session_id=session.session_id,
        organization_id=organization.organization_id,
        expected_revision_id=current.revision_id,
        message_id=message.message_id,
    )


@pytest.mark.parametrize(
    "text",
    (
        "I want a white-gold engagement ring with an oval center stone.",
        "Хочу помолвочное кольцо из белого золота с овальным центральным камнем.",
    ),
)
def test_internal_parse_revision_enrichment_and_snapshot_are_one_coherent_flow(
    engine, tmp_path, text
):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, text)
    runtime, store, active, report = _runtime(service, tmp_path)

    result = runtime.start_initial_message(request)
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    cycles = service.repository.list_enrichment_cycles(
        session.session_id, organization.organization_id
    )
    snapshot = build_final_prompt_snapshot(
        service.repository,
        session_id=session.session_id,
        organization_id=organization.organization_id,
        artifacts=service.artifacts,
        artifact_store=store,
        active_release=active,
        validation_report=report,
    )

    assert result.parse_result.original_text == text
    assert result.parser_proposal.source.message_id == str(request.message_id)
    assert current.revision_id == result.workflow.authoritative_revision_id
    assert len(cycles) == 1
    assert cycles[0].specification_revision_id == current.revision_id
    assert snapshot.revision == current
    assert snapshot.enrichment_result == cycles[0].result
    assert snapshot.knowledge_release.runtime_sha256 == active.runtime_sha256
    assert result.workflow.final_output is not None


def test_current_handoff_is_scoped_deterministic_restart_safe_and_read_only(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    foreign, _, _ = create_persisted_session(service)
    runtime, store, active, report = _runtime(service, tmp_path)
    runtime.start_initial_message(
        _request(service, organization, session, "Create an oval ring without engraving.")
    )
    cycles_before = service.repository.list_enrichment_cycles(
        session.session_id, organization.organization_id
    )
    revisions_before = service.repository.list_revisions(
        session.session_id, organization.organization_id
    )

    first = runtime.build_current_internal_final_prompt_handoff(
        session.session_id, organization.organization_id
    )
    repeated = runtime.build_current_internal_final_prompt_handoff(
        session.session_id, organization.organization_id
    )
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
    restored = restarted.build_current_internal_final_prompt_handoff(
        session.session_id, organization.organization_id
    )

    assert first == repeated == restored
    assert first.organization_id == organization.organization_id
    assert first.session_id == session.session_id
    assert first.internal_final_prompt_content_hash == first.internal_final_prompt.content_hash
    assert any(
        item.target == "feature.engraving" and item.kind == "prohibition"
        for item in first.internal_final_prompt.constraints
    )
    assert (
        service.repository.list_enrichment_cycles(session.session_id, organization.organization_id)
        == cycles_before
    )
    assert (
        service.repository.list_revisions(session.session_id, organization.organization_id)
        == revisions_before
    )

    with pytest.raises(PromptEnrichmentRuntimeError) as cross_scope:
        runtime.build_current_internal_final_prompt_handoff(
            session.session_id, foreign.organization_id
        )
    assert cross_scope.value.code == PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND

    with pytest.raises(PromptEnrichmentRuntimeError) as missing:
        runtime.build_current_internal_final_prompt_handoff(uuid4(), organization.organization_id)
    assert missing.value.code == PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND


def test_current_handoff_reconstruction_is_concurrent_and_equivalent(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    runtime, *_ = _runtime(service, tmp_path)
    runtime.start_initial_message(
        _request(service, organization, session, "Create an oval white-gold ring.")
    )

    def build(_):
        return runtime.build_current_internal_final_prompt_handoff(
            session.session_id, organization.organization_id
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(build, range(2)))

    assert results[0] == results[1]


def test_correction_changes_current_handoff_without_reusing_stale_authority(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    runtime, *_ = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(
        _request(service, organization, session, "Create an oval white-gold ring.")
    )
    previous = runtime.build_current_internal_final_prompt_handoff(
        session.session_id, organization.organization_id
    )
    message = service.create_message(
        session.session_id,
        organization.organization_id,
        "Change the center stone to emerald cut.",
    )

    runtime.apply_persisted_user_correction(
        organization.organization_id,
        PersistedUserCorrectionRequest(
            session_id=session.session_id,
            expected_revision_id=initial.workflow.authoritative_revision_id,
            message_id=message.message_id,
        ),
    )
    current = runtime.build_current_internal_final_prompt_handoff(
        session.session_id, organization.organization_id
    )

    assert current.product_state_revision_id != previous.product_state_revision_id
    assert current.enrichment_cycle_id != previous.enrichment_cycle_id
    assert current.internal_final_prompt_content_hash != previous.internal_final_prompt_content_hash
    assert current.content_hash != previous.content_hash


def test_stale_and_cross_organization_initial_requests_fail_closed(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    foreign, _, _ = create_persisted_session(service)
    request = _request(service, organization, session, "I want an oval ring.")
    runtime, *_ = _runtime(service, tmp_path)

    with pytest.raises(PromptEnrichmentRuntimeError) as cross_scope:
        runtime.start_initial_message(
            request.model_copy(update={"organization_id": foreign.organization_id})
        )
    assert cross_scope.value.code == PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND

    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    advanced = next_revision(current, "round")
    service.repository.append_revision_cas(
        session.session_id,
        organization.organization_id,
        current.revision_id,
        advanced,
    )
    with pytest.raises(PromptEnrichmentRuntimeError) as stale:
        runtime.start_initial_message(request)
    assert stale.value.code == PromptEnrichmentRuntimeErrorCode.STALE_REVISION


def test_initial_revision_and_cycle_roll_back_together(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(
        service,
        organization,
        session,
        "I want a white-gold engagement ring with an oval center stone.",
    )
    runtime, *_ = _runtime(service, tmp_path)
    original = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )

    def reject_cycle(mapper, connection, target):
        raise RuntimeError("simulated cycle write failure")

    event.listen(EnrichmentCycleRow, "before_insert", reject_cycle)
    try:
        with pytest.raises(RuntimeError, match="simulated cycle write failure"):
            runtime.start_initial_message(request)
    finally:
        event.remove(EnrichmentCycleRow, "before_insert", reject_cycle)

    assert (
        service.repository.get_current_revision(session.session_id, organization.organization_id)
        == original
    )
    assert service.repository.list_revisions(session.session_id, organization.organization_id) == (
        original,
    )
    with create_session_factory(engine)() as db:
        assert db.scalar(select(func.count()).select_from(EnrichmentCycleRow)) == 0


def test_complete_plan_is_persisted_and_restored_after_runtime_restart(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, "I want a white or yellow gold ring.")
    runtime, store, active, report = _runtime(service, tmp_path)

    initial = runtime.start_initial_message(request)
    plan = initial.workflow.clarification_plan
    assert plan is not None
    assert initial.workflow.clarification_plan_id is not None
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

    restored = restarted.restore_clarification_plan(
        session.session_id,
        organization.organization_id,
        initial.workflow.clarification_plan_id,
        require_current=True,
    )
    state = restarted.get_current_state(session.session_id, organization.organization_id)

    assert restored == plan
    assert restored.content_hash == plan.content_hash
    assert restored.questions == plan.questions
    assert restored.questions[0].options == plan.questions[0].options
    assert restored.questions[0].evidence == plan.questions[0].evidence
    assert state.clarification_plan == plan
    assert state.clarification_plan_id == initial.workflow.clarification_plan_id


def test_plan_insert_failure_rolls_back_revision_pin_and_cycle(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(
        service,
        organization,
        session,
        "I want a white-gold engagement ring with an oval center stone.",
    )
    runtime, *_ = _runtime(service, tmp_path)
    original = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )

    def reject_plan(mapper, connection, target):
        raise RuntimeError("simulated plan write failure")

    event.listen(ClarificationPlanRow, "before_insert", reject_plan)
    try:
        with pytest.raises(RuntimeError, match="simulated plan write failure"):
            runtime.start_initial_message(request)
    finally:
        event.remove(ClarificationPlanRow, "before_insert", reject_plan)

    assert (
        service.repository.get_current_revision(session.session_id, organization.organization_id)
        == original
    )
    assert service.repository.list_revisions(session.session_id, organization.organization_id) == (
        original,
    )
    with create_session_factory(engine)() as db:
        assert db.scalar(select(func.count()).select_from(EnrichmentCycleRow)) == 0
        assert db.scalar(select(func.count()).select_from(ClarificationPlanRow)) == 0


def test_persisted_answer_is_restart_safe_idempotent_and_rejects_conflict(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, "I want a white or yellow gold ring.")
    runtime, store, active, report = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(request)
    plan = initial.workflow.clarification_plan
    assert plan is not None
    question = next(item for item in plan.questions if len(item.options) >= 2)
    message = service.create_message(
        session.session_id, organization.organization_id, question.options[0].value
    )
    answer_id = uuid4()
    persisted = PersistedClarificationAnswerRequest(
        session_id=session.session_id,
        clarification_plan_id=initial.workflow.clarification_plan_id,
        clarification_id=question.clarification_id,
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option=question.options[0].value,
        expected_revision_id=initial.workflow.authoritative_revision_id,
        answer_id=answer_id,
        message_id=message.message_id,
    )
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

    result, state = restarted.record_persisted_clarification_answer(
        organization.organization_id, persisted
    )
    retry, retry_state = restarted.record_persisted_clarification_answer(
        organization.organization_id, persisted
    )

    assert retry == result
    assert retry_state == state
    assert (
        len(
            service.repository.list_clarification_answers(
                session.session_id, organization.organization_id
            )
        )
        == 1
    )
    assert (
        len(
            service.repository.list_enrichment_cycles(
                session.session_id, organization.organization_id
            )
        )
        == 2
    )
    assert (
        len(
            service.repository.list_clarification_plans(
                session.session_id, organization.organization_id
            )
        )
        == 2
    )

    conflicting = persisted.model_copy(
        update={"selected_option": question.options[1].value, "answer_id": uuid4()}
    )
    with pytest.raises(PromptEnrichmentRuntimeError) as conflict:
        restarted.record_persisted_clarification_answer(organization.organization_id, conflicting)
    assert conflict.value.code == PromptEnrichmentRuntimeErrorCode.CLARIFICATION_CONFLICT

    stale_question = next(
        item for item in plan.questions if item.clarification_id != question.clarification_id
    )
    stale_message = service.create_message(
        session.session_id, organization.organization_id, "I do not know."
    )
    stale = PersistedClarificationAnswerRequest(
        session_id=session.session_id,
        clarification_plan_id=initial.workflow.clarification_plan_id,
        clarification_id=stale_question.clarification_id,
        decision=ClarificationDecision.UNKNOWN,
        expected_revision_id=state.authoritative_revision_id,
        answer_id=uuid4(),
        message_id=stale_message.message_id,
    )
    with pytest.raises(PromptEnrichmentRuntimeError) as stale_error:
        restarted.record_persisted_clarification_answer(organization.organization_id, stale)
    assert stale_error.value.code == PromptEnrichmentRuntimeErrorCode.STALE_CLARIFICATION_PLAN


def test_tampered_and_cross_organization_plans_fail_closed(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    foreign, _, _ = create_persisted_session(service)
    runtime, *_ = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(
        _request(service, organization, session, "I want a white or yellow gold ring.")
    )
    plan_id = initial.workflow.clarification_plan_id

    with pytest.raises(PromptEnrichmentRuntimeError) as cross_scope:
        runtime.restore_clarification_plan(
            session.session_id, foreign.organization_id, plan_id, require_current=False
        )
    assert cross_scope.value.code == PromptEnrichmentRuntimeErrorCode.SESSION_NOT_FOUND

    with create_session_factory(engine).begin() as db:
        row = db.get(ClarificationPlanRow, plan_id)
        row.plan_payload = {**row.plan_payload, "content_hash": "0" * 64}

    with pytest.raises(PromptEnrichmentRuntimeError) as corrupt:
        runtime.restore_clarification_plan(
            session.session_id, organization.organization_id, plan_id, require_current=False
        )
    assert corrupt.value.code == PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN


def test_tampered_constraint_evidence_and_legacy_plan_fail_closed(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    runtime, *_ = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(
        _request(service, organization, session, "Create a ring with no halo.")
    )
    plan_id = initial.workflow.clarification_plan_id

    with create_session_factory(engine).begin() as db:
        row = db.get(ClarificationPlanRow, plan_id)
        payload = dict(row.plan_payload)
        evidence = [dict(item) for item in payload["constraint_evidence"]]
        evidence[0]["original_wording"] = "tampered wording"
        payload["constraint_evidence"] = evidence
        unsigned = {key: value for key, value in payload.items() if key != "content_hash"}
        payload["content_hash"] = _content_hash(unsigned)
        row.plan_payload = payload

    with pytest.raises(PromptEnrichmentRuntimeError) as tampered:
        runtime.restore_clarification_plan(
            session.session_id, organization.organization_id, plan_id, require_current=False
        )
    assert tampered.value.code == PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN

    legacy_service = build_service(engine)
    legacy_organization, _, legacy_session = create_persisted_session(legacy_service)
    legacy_runtime, *_ = _runtime(legacy_service, tmp_path / "legacy")
    legacy = legacy_runtime.start_initial_message(
        _request(legacy_service, legacy_organization, legacy_session, "Create an oval ring.")
    )
    with create_session_factory(engine).begin() as db:
        row = db.get(ClarificationPlanRow, legacy.workflow.clarification_plan_id)
        payload = dict(row.plan_payload)
        payload["plan_version"] = "1.0.0"
        payload.pop("constraint_evidence")
        unsigned = {key: value for key, value in payload.items() if key != "content_hash"}
        payload["content_hash"] = _content_hash(unsigned)
        row.plan_payload = payload

    with pytest.raises(PromptEnrichmentRuntimeError) as incompatible:
        legacy_runtime.restore_clarification_plan(
            legacy_session.session_id,
            legacy_organization.organization_id,
            legacy.workflow.clarification_plan_id,
            require_current=False,
        )
    assert incompatible.value.code == PromptEnrichmentRuntimeErrorCode.INVALID_CLARIFICATION_PLAN


def test_snapshot_rejects_a_cycle_from_an_old_revision(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, "I want an oval ring.")
    runtime, *_ = _runtime(service, tmp_path)
    runtime.start_initial_message(request)
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    advanced = next_revision(current, "round")
    service.repository.append_revision_cas(
        session.session_id,
        organization.organization_id,
        current.revision_id,
        advanced,
    )

    with pytest.raises(PromptEnrichmentRuntimeError) as mismatch:
        runtime.get_current_state(session.session_id, organization.organization_id)
    assert mismatch.value.code == PromptEnrichmentRuntimeErrorCode.ENRICHMENT_CYCLE_MISMATCH


def test_explicit_release_mismatch_never_falls_forward(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, "I want an oval ring.")
    runtime, _, active, _ = _runtime(service, tmp_path)
    runtime.active_release = active.model_copy(update={"runtime_sha256": "0" * 64})

    with pytest.raises(PromptEnrichmentRuntimeError) as invalid:
        runtime.start_initial_message(request)
    assert invalid.value.code == PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE
    with create_session_factory(engine)() as db:
        assert db.scalar(select(func.count()).select_from(EnrichmentCycleRow)) == 0


def test_clarification_answer_revision_and_reenrichment_commit_atomically(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, "I want a white or yellow gold ring.")
    runtime, *_ = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(request)
    plan = initial.workflow.clarification_plan
    assert plan is not None
    question = next(item for item in plan.questions if len(item.options) >= 2)
    selected = question.options[0]
    answer = ClarificationAnswer(
        session_id=session.session_id,
        plan_content_hash=plan.content_hash,
        clarification_id=question.clarification_id,
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option=selected.value,
        expected_revision_id=initial.workflow.authoritative_revision_id,
        knowledge_package_id=initial.workflow.knowledge_release.package_id,
        knowledge_artifact_version=initial.workflow.knowledge_release.artifact_version,
        knowledge_runtime_sha256=initial.workflow.knowledge_release.runtime_sha256,
        knowledge_validation_report_sha256=(
            initial.workflow.knowledge_release.validation_report_sha256
        ),
        source=MessageSource(message_id="clarification-answer-1", recorded_at=NOW),
    )

    result, state = runtime.record_clarification_answer(organization.organization_id, plan, answer)
    retry, retry_state = runtime.record_clarification_answer(
        organization.organization_id, plan, answer
    )
    cycles = service.repository.list_enrichment_cycles(
        session.session_id, organization.organization_id
    )

    assert result.resulting_revision is not None
    assert retry == result
    assert retry_state.authoritative_revision_id == state.authoritative_revision_id
    assert state.authoritative_revision_id == result.new_revision_id
    assert len(cycles) == 2
    assert cycles[-1].specification_revision_id == result.new_revision_id
    assert cycles[-1].result.design_revision_id == str(result.new_revision_id)
    assert (
        len(
            service.repository.list_clarification_answers(
                session.session_id, organization.organization_id
            )
        )
        == 1
    )


def test_scoped_user_correction_reuses_durable_cas_and_latest_cycle(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, "I want an oval white-gold ring.")
    runtime, *_ = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(request)
    design_before = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    ).design
    cycle = service.repository.list_enrichment_cycles(
        session.session_id, organization.organization_id
    )[-1]
    message = service.create_message(
        session.session_id,
        organization.organization_id,
        "Change the center stone to emerald cut, but keep the original band.",
    )
    correction = UserCorrection(
        session_id=session.session_id,
        expected_revision_id=initial.workflow.authoritative_revision_id,
        correction_text=message.content,
        locale="en",
        source=MessageSource(message_id=str(message.message_id), recorded_at=NOW),
        previous_enrichment_cycle_id=cycle.enrichment_cycle_id,
        previous_enrichment_cycle_number=cycle.cycle_number,
        previous_enrichment_content_hash=cycle.result.content_hash,
        knowledge_package_id=cycle.release_pin.package_id,
        knowledge_artifact_version=cycle.release_pin.artifact_version,
        knowledge_runtime_sha256=cycle.release_pin.runtime_sha256,
        knowledge_validation_report_sha256=cycle.release_pin.validation_report_sha256,
        dictionary_artifact_version=service.artifacts.versions.dictionary,
        prompt_template_artifact_version=service.artifacts.versions.prompts,
    )

    result, state = runtime.apply_scoped_user_correction(organization.organization_id, correction)
    retry, retry_state = runtime.apply_scoped_user_correction(
        organization.organization_id, correction
    )
    cycles = service.repository.list_enrichment_cycles(
        session.session_id, organization.organization_id
    )

    assert result.next_enrichment_cycle_number == 2
    assert retry == result
    assert retry_state.authoritative_revision_id == state.authoritative_revision_id
    assert len(cycles) == 2
    assert cycles[-1].specification_revision_id == state.authoritative_revision_id
    assert state.final_output is not None
    assert (
        state.final_output.description.authoritative_revision_id == state.authoritative_revision_id
    )
    current = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )
    assert current.design.center_stone.shape.value == "emerald_cut"
    assert current.design.metal == design_before.metal
    assert current.design.construction == design_before.construction
    preservation = next(
        item
        for item in state.clarification_plan.constraint_evidence
        if item.semantic_subject == "component.band" and item.status == "active"
    )
    assert preservation.kind == "preservation"
    assert any(
        item.target == "component.band" and item.kind == "preservation"
        for item in state.final_output.internal_final_prompt.constraints
    )


def test_user_correction_supersedes_non_schema_constraint_without_conflict(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    runtime, *_ = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(
        _request(service, organization, session, "Create an oval ring with no halo.")
    )
    cycle = service.repository.list_enrichment_cycles(
        session.session_id, organization.organization_id
    )[-1]
    message = service.create_message(
        session.session_id,
        organization.organization_id,
        "Actually, add a halo.",
    )
    correction = UserCorrection(
        session_id=session.session_id,
        expected_revision_id=initial.workflow.authoritative_revision_id,
        correction_text=message.content,
        locale="en",
        source=MessageSource(message_id=str(message.message_id), recorded_at=NOW),
        previous_enrichment_cycle_id=cycle.enrichment_cycle_id,
        previous_enrichment_cycle_number=cycle.cycle_number,
        previous_enrichment_content_hash=cycle.result.content_hash,
        knowledge_package_id=cycle.release_pin.package_id,
        knowledge_artifact_version=cycle.release_pin.artifact_version,
        knowledge_runtime_sha256=cycle.release_pin.runtime_sha256,
        knowledge_validation_report_sha256=cycle.release_pin.validation_report_sha256,
        dictionary_artifact_version=service.artifacts.versions.dictionary,
        prompt_template_artifact_version=service.artifacts.versions.prompts,
    )

    _, state = runtime.apply_scoped_user_correction(organization.organization_id, correction)

    halo = [
        item
        for item in state.clarification_plan.constraint_evidence
        if item.semantic_subject == "feature.halo"
    ]
    assert len(halo) == 2
    assert {item.status for item in halo} == {"active", "superseded"}
    assert next(item for item in halo if item.status == "active").kind == "requirement"
    assert state.final_output is not None
    active_constraints = [
        item
        for item in state.final_output.internal_final_prompt.constraints
        if item.target == "feature.halo"
    ]
    assert len(active_constraints) == 1
    assert active_constraints[0].kind == "requirement"
    assert "Do not include a halo" not in state.final_output.internal_final_prompt.prompt_text


def test_clarification_revision_answer_and_cycle_roll_back_together(engine, tmp_path):
    service = build_service(engine)
    organization, _, session = create_persisted_session(service)
    request = _request(service, organization, session, "I want a white or yellow gold ring.")
    runtime, *_ = _runtime(service, tmp_path)
    initial = runtime.start_initial_message(request)
    plan = initial.workflow.clarification_plan
    assert plan is not None
    question = next(item for item in plan.questions if len(item.options) >= 2)
    answer = ClarificationAnswer(
        session_id=session.session_id,
        plan_content_hash=plan.content_hash,
        clarification_id=question.clarification_id,
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option=question.options[0].value,
        expected_revision_id=initial.workflow.authoritative_revision_id,
        knowledge_package_id=initial.workflow.knowledge_release.package_id,
        knowledge_artifact_version=initial.workflow.knowledge_release.artifact_version,
        knowledge_runtime_sha256=initial.workflow.knowledge_release.runtime_sha256,
        knowledge_validation_report_sha256=(
            initial.workflow.knowledge_release.validation_report_sha256
        ),
        source=MessageSource(message_id="clarification-answer-rollback", recorded_at=NOW),
    )
    before = service.repository.get_current_revision(
        session.session_id, organization.organization_id
    )

    def reject_second_cycle(mapper, connection, target):
        if target.cycle_number == 2:
            raise RuntimeError("simulated answer cycle failure")

    event.listen(EnrichmentCycleRow, "before_insert", reject_second_cycle)
    try:
        with pytest.raises(RuntimeError, match="simulated answer cycle failure"):
            runtime.record_clarification_answer(organization.organization_id, plan, answer)
    finally:
        event.remove(EnrichmentCycleRow, "before_insert", reject_second_cycle)

    assert (
        service.repository.get_current_revision(session.session_id, organization.organization_id)
        == before
    )
    assert (
        len(
            service.repository.list_enrichment_cycles(
                session.session_id, organization.organization_id
            )
        )
        == 1
    )
    assert (
        service.repository.list_clarification_answers(
            session.session_id, organization.organization_id
        )
        == ()
    )


@pytest.mark.postgres
def test_postgres_concurrent_initial_orchestration_commits_one_complete_history(tmp_path):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL concurrency coverage")
    pg_engine = create_database_engine(database_url)
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    try:
        service = build_service(pg_engine)
        organization, _, session = create_persisted_session(service)
        request = _request(
            service,
            organization,
            session,
            "I want a white-gold engagement ring with an oval center stone.",
        )
        runtime, *_ = _runtime(service, tmp_path)

        def run_once():
            try:
                runtime.start_initial_message(request)
                return "success"
            except PromptEnrichmentRuntimeError as exc:
                assert exc.code in {
                    PromptEnrichmentRuntimeErrorCode.STALE_REVISION,
                    PromptEnrichmentRuntimeErrorCode.CONCURRENT_CONFLICT,
                }
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(lambda _: run_once(), range(2)))

        assert sorted(outcomes) == ["conflict", "success"]
        cycles = service.repository.list_enrichment_cycles(
            session.session_id, organization.organization_id
        )
        revisions = service.repository.list_revisions(
            session.session_id, organization.organization_id
        )
        assert len(cycles) == 1
        plans = service.repository.list_clarification_plans(
            session.session_id, organization.organization_id
        )
        assert len(plans) == 1
        assert plans[0].enrichment_cycle_id == cycles[0].enrichment_cycle_id
        assert len(revisions) == 2
        assert cycles[0].specification_revision_id == revisions[-1].revision_id
    finally:
        pg_engine.dispose()


@pytest.mark.postgres
def test_postgres_concurrent_persisted_answers_commit_one_cycle_and_plan(tmp_path):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL concurrency coverage")
    pg_engine = create_database_engine(database_url)
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    try:
        service = build_service(pg_engine)
        organization, _, session = create_persisted_session(service)
        runtime, *_ = _runtime(service, tmp_path)
        initial = runtime.start_initial_message(
            _request(service, organization, session, "I want a white or yellow gold ring.")
        )
        plan = initial.workflow.clarification_plan
        question = next(item for item in plan.questions if len(item.options) >= 2)
        messages = tuple(
            service.create_message(session.session_id, organization.organization_id, option.value)
            for option in question.options[:2]
        )

        def answer(index):
            request = PersistedClarificationAnswerRequest(
                session_id=session.session_id,
                clarification_plan_id=initial.workflow.clarification_plan_id,
                clarification_id=question.clarification_id,
                decision=ClarificationDecision.SELECT_OPTION,
                selected_option=question.options[index].value,
                expected_revision_id=initial.workflow.authoritative_revision_id,
                answer_id=uuid4(),
                message_id=messages[index].message_id,
            )
            try:
                runtime.record_persisted_clarification_answer(organization.organization_id, request)
                return "success"
            except PromptEnrichmentRuntimeError as exc:
                assert exc.code in {
                    PromptEnrichmentRuntimeErrorCode.CLARIFICATION_CONFLICT,
                    PromptEnrichmentRuntimeErrorCode.CONCURRENT_CONFLICT,
                    PromptEnrichmentRuntimeErrorCode.STALE_CLARIFICATION_PLAN,
                }
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(answer, range(2)))

        assert sorted(outcomes) == ["conflict", "success"]
        assert (
            len(
                service.repository.list_clarification_answers(
                    session.session_id, organization.organization_id
                )
            )
            == 1
        )
        assert (
            len(
                service.repository.list_enrichment_cycles(
                    session.session_id, organization.organization_id
                )
            )
            == 2
        )
        assert (
            len(
                service.repository.list_clarification_plans(
                    session.session_id, organization.organization_id
                )
            )
            == 2
        )
    finally:
        Base.metadata.drop_all(pg_engine)
        pg_engine.dispose()


@pytest.mark.postgres
def test_postgres_conflicting_corrections_commit_no_partial_constraint_history(tmp_path):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL correction concurrency coverage")
    pg_engine = create_database_engine(database_url)
    Base.metadata.drop_all(pg_engine)
    Base.metadata.create_all(pg_engine)
    try:
        service = build_service(pg_engine)
        organization, _, session = create_persisted_session(service)
        runtime, *_ = _runtime(service, tmp_path)
        initial = runtime.start_initial_message(
            _request(service, organization, session, "Create an oval ring with no halo.")
        )
        cycle = service.repository.list_enrichment_cycles(
            session.session_id, organization.organization_id
        )[-1]
        messages = (
            service.create_message(
                session.session_id,
                organization.organization_id,
                "Change the center stone to emerald cut and add a halo.",
            ),
            service.create_message(
                session.session_id,
                organization.organization_id,
                "Change the metal to platinum and keep the ring without a halo.",
            ),
        )

        def correct(message):
            request = UserCorrection(
                session_id=session.session_id,
                expected_revision_id=initial.workflow.authoritative_revision_id,
                correction_text=message.content,
                locale="en",
                source=MessageSource(message_id=str(message.message_id), recorded_at=NOW),
                previous_enrichment_cycle_id=cycle.enrichment_cycle_id,
                previous_enrichment_cycle_number=cycle.cycle_number,
                previous_enrichment_content_hash=cycle.result.content_hash,
                knowledge_package_id=cycle.release_pin.package_id,
                knowledge_artifact_version=cycle.release_pin.artifact_version,
                knowledge_runtime_sha256=cycle.release_pin.runtime_sha256,
                knowledge_validation_report_sha256=cycle.release_pin.validation_report_sha256,
                dictionary_artifact_version=service.artifacts.versions.dictionary,
                prompt_template_artifact_version=service.artifacts.versions.prompts,
            )
            try:
                runtime.apply_scoped_user_correction(organization.organization_id, request)
                return "success"
            except PromptEnrichmentRuntimeError as exc:
                assert exc.code in {
                    PromptEnrichmentRuntimeErrorCode.STALE_REVISION,
                    PromptEnrichmentRuntimeErrorCode.CONCURRENT_CONFLICT,
                }
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(correct, messages))

        assert sorted(outcomes) == ["conflict", "success"]
        cycles = service.repository.list_enrichment_cycles(
            session.session_id, organization.organization_id
        )
        plans = service.repository.list_clarification_plans(
            session.session_id, organization.organization_id
        )
        corrections = service.repository.list_user_corrections(
            session.session_id, organization.organization_id
        )
        assert len(cycles) == len(plans) == 2
        assert len(corrections) == 1
        current = runtime.get_current_state(session.session_id, organization.organization_id)
        halo = [
            item
            for item in current.clarification_plan.constraint_evidence
            if item.semantic_subject == "feature.halo"
        ]
        assert len([item for item in halo if item.status == "active"]) == 1
        assert len([item for item in halo if item.status == "superseded"]) == 1
    finally:
        Base.metadata.drop_all(pg_engine)
        pg_engine.dispose()
