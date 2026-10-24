import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from jewelai_domain import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ProductionValidationCheck,
    ProductionValidationReport,
    compile_knowledge_library,
    load_domain_dictionary,
    load_parametric_knowledge,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore
from jewelai_domain.models import DesignRevision, MessageSource
from jewelai_domain.questions import QuestionId
from jewelai_parser import CandidateClassification, CandidateSubject
from jewelai_persistence import EnrichmentCycleRecord, KnowledgeReleasePinRecord
from jewelai_prompts import enrich_prompt_with_active_release, load_prompt_templates

from jewelai_api.clarification_answers import (
    ClarificationAnswerOutcome,
    ClarificationAnswerReason,
    ClarificationAnswerResult,
    ClarificationDecision,
)
from jewelai_api.clarification_answers import (
    _hash as answer_hash,
)
from jewelai_api.clarification_answers import (
    _json as answer_json,
)
from jewelai_api.correction_enrichment import (
    CorrectionErrorCode,
    CorrectionInputError,
    CorrectionOutcome,
    CorrectionReason,
    UserCorrection,
    process_user_correction,
)
from jewelai_api.parsed_enrichment import CandidateDispositionReason

ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
DICTIONARY = ROOT / "data" / "dictionary" / "v1.0.0.json"
PROMPTS = ROOT / "data" / "prompts" / "v1.0.0.json"
PARAMETRIC = ROOT / "data" / "knowledge-base" / "v1.0.0.json"
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
NOW = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
SESSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CYCLE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(DICTIONARY)


@pytest.fixture(scope="module")
def templates():
    return load_prompt_templates(PROMPTS)


@pytest.fixture
def revision():
    return DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))


@pytest.fixture
def active_context(tmp_path, revision, templates):
    payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    stored = store.publish(payload)
    runtime, _ = compile_knowledge_library(payload)
    report = ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome="PASS",
                evidence_ref=f"ci://correction/{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )
    active = promote_knowledge_runtime(runtime, report)
    parametric = load_parametric_knowledge(PARAMETRIC)
    result = enrich_prompt_with_active_release(
        revision,
        templates,
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        parametric_catalog_id=parametric.catalog_id,
        parametric_artifact_version=str(parametric.artifact_version),
        parametric_catalog_sha256=parametric.sha256,
    )
    pin = KnowledgeReleasePinRecord(
        session_id=SESSION_ID,
        package_id=stored.package_id,
        artifact_version=stored.artifact_version,
        runtime_sha256=active.runtime_sha256,
        validation_report_sha256=active.validation_report_sha256,
    )
    cycle = EnrichmentCycleRecord(
        enrichment_cycle_id=CYCLE_ID,
        session_id=SESSION_ID,
        cycle_number=3,
        specification_revision_id=revision.revision_id,
        release_pin=pin,
        result=result,
        created_at=NOW,
    )
    return store, stored, report, active, cycle


def _source(message_id="correction-message"):
    return MessageSource(message_id=message_id, recorded_at=NOW)


def _request(text, revision, context, dictionary, templates, *, locale="en", **changes):
    _, stored, report, active, cycle = context
    payload = {
        "session_id": SESSION_ID,
        "expected_revision_id": revision.revision_id,
        "correction_text": text,
        "locale": locale,
        "source": _source(),
        "previous_enrichment_cycle_id": cycle.enrichment_cycle_id,
        "previous_enrichment_cycle_number": cycle.cycle_number,
        "previous_enrichment_content_hash": cycle.result.content_hash,
        "knowledge_package_id": stored.package_id,
        "knowledge_artifact_version": stored.artifact_version,
        "knowledge_runtime_sha256": active.runtime_sha256,
        "knowledge_validation_report_sha256": report.sha256,
        "dictionary_artifact_version": dictionary.artifact_version,
        "prompt_template_artifact_version": str(templates.artifact_version),
    }
    payload.update(changes)
    return UserCorrection.model_validate(payload)


def _process(request, revision, context, dictionary, templates, **changes):
    store, _, report, active, cycle = context
    options = {
        "authoritative_session_id": SESSION_ID,
        "current_revision": revision,
        "previous_cycle": cycle,
        "prior_answer_results": (),
        "dictionary": dictionary,
        "templates": templates,
        "artifact_store": store,
        "active_release": active,
        "validation_report": report,
        "parametric_knowledge": load_parametric_knowledge(PARAMETRIC),
        "created_at": NOW,
    }
    options.update(changes)
    return process_user_correction(request, **options)


def _context_for_revision(context, revision, templates):
    store, stored, report, active, cycle = context
    parametric = load_parametric_knowledge(PARAMETRIC)
    result = enrich_prompt_with_active_release(
        revision,
        templates,
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        parametric_catalog_id=parametric.catalog_id,
        parametric_artifact_version=str(parametric.artifact_version),
        parametric_catalog_sha256=parametric.sha256,
    )
    return (
        store,
        stored,
        report,
        active,
        EnrichmentCycleRecord(
            enrichment_cycle_id=cycle.enrichment_cycle_id,
            session_id=cycle.session_id,
            cycle_number=cycle.cycle_number,
            specification_revision_id=revision.revision_id,
            release_pin=cycle.release_pin,
            result=result,
            created_at=cycle.created_at,
        ),
    )


def _revision_with(revision, *path, value):
    payload = revision.model_dump(mode="json")
    cursor = payload["design"]
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    return DesignRevision.model_validate(payload)


def _rejected_answer(context, revision):
    _, stored, report, active, cycle = context
    payload = {
        "answer_version": "1.0.0",
        "session_id": SESSION_ID,
        "plan_content_hash": "1" * 64,
        "clarification_id": "clarification_recommendation_halo",
        "semantic_question_id": QuestionId.CENTER_STONE_SETTING,
        "decision": ClarificationDecision.REJECT,
        "selected_option": None,
        "source_candidate_ids": (),
        "source_proposal_ids": ("recommendation-halo",),
        "evidence": (),
        "target": "center_stone.setting",
        "subject": None,
        "previous_revision_id": revision.revision_id,
        "new_revision_id": None,
        "resulting_revision": None,
        "knowledge_package_id": stored.package_id,
        "knowledge_artifact_version": stored.artifact_version,
        "knowledge_runtime_sha256": active.runtime_sha256,
        "knowledge_validation_report_sha256": report.sha256,
        "question_artifact_version": "1.0.0",
        "rules_artifact_version": "1.0.0",
        "outcome": ClarificationAnswerOutcome.REJECTED,
        "reason": ClarificationAnswerReason.USER_REJECTED_OFFER,
        "question_resolved": True,
        "blocks_progression": False,
        "answer_hash": hashlib.sha256(b"reject-halo").hexdigest(),
    }
    return ClarificationAnswerResult(
        **payload,
        content_hash=answer_hash(answer_json(payload)),
    )


def _accepted_no_change_answer(context, revision):
    _, stored, report, active, _ = context
    payload = {
        "answer_version": "1.0.0",
        "session_id": SESSION_ID,
        "plan_content_hash": "2" * 64,
        "clarification_id": "clarification_accept_existing_setting",
        "semantic_question_id": QuestionId.CENTER_STONE_SETTING,
        "decision": ClarificationDecision.ACCEPT,
        "selected_option": None,
        "source_candidate_ids": (),
        "source_proposal_ids": ("existing-prong-setting",),
        "evidence": (),
        "target": "center_stone.setting",
        "subject": None,
        "previous_revision_id": revision.revision_id,
        "new_revision_id": None,
        "resulting_revision": None,
        "knowledge_package_id": stored.package_id,
        "knowledge_artifact_version": stored.artifact_version,
        "knowledge_runtime_sha256": active.runtime_sha256,
        "knowledge_validation_report_sha256": report.sha256,
        "question_artifact_version": "1.0.0",
        "rules_artifact_version": "1.0.0",
        "outcome": ClarificationAnswerOutcome.NO_CHANGE,
        "reason": ClarificationAnswerReason.VALUE_ALREADY_CURRENT,
        "question_resolved": True,
        "blocks_progression": False,
        "answer_hash": hashlib.sha256(b"accept-existing-setting").hexdigest(),
    }
    return ClarificationAnswerResult(
        **payload,
        content_hash=answer_hash(answer_json(payload)),
    )


def test_english_correction_replaces_only_supported_value_and_reenriches(
    revision, active_context, dictionary, templates
):
    text = "Change the center stone to emerald cut, but keep the white gold."
    request = _request(text, revision, active_context, dictionary, templates)
    before = copy.deepcopy(revision)

    result = _process(request, revision, active_context, dictionary, templates)

    assert result.outcome == CorrectionOutcome.APPLIED
    assert result.reason == CorrectionReason.SUPPORTED_CHANGES_APPLIED
    assert result.correction_text == text
    assert result.parsed_correction.original_text == text
    assert result.authoritative_revision.design.center_stone.shape.value == "emerald_cut"
    assert result.authoritative_revision.design.center_stone.shape.confirmed is False
    assert result.authoritative_revision.design.center_stone.shape.source == request.source
    assert result.authoritative_revision.design.metal == revision.design.metal
    assert result.authoritative_revision.design.side_stones == revision.design.side_stones
    assert result.next_enrichment_result.design_revision_id == str(result.new_revision_id)
    assert result.next_enrichment_cycle_number == 4
    assert revision == before


@pytest.mark.parametrize(
    ("text", "locale", "expected_language"),
    [
        ("Сделай центральный камень изумрудной огранки.", "ru", "ru"),
        ("Сделай center stone emerald-cut.", "ru", "mixed"),
    ],
)
def test_russian_and_mixed_language_corrections_use_internal_parser(
    text,
    locale,
    expected_language,
    revision,
    active_context,
    dictionary,
    templates,
):
    request = _request(
        text,
        revision,
        active_context,
        dictionary,
        templates,
        locale=locale,
    )

    result = _process(request, revision, active_context, dictionary, templates)

    assert result.outcome == CorrectionOutcome.APPLIED
    assert result.parsed_correction.detected_language.value == expected_language
    assert result.authoritative_revision.design.center_stone.shape.value == "emerald_cut"


def test_new_supported_requirement_is_applied_without_inventing_dimensions(
    revision, active_context, dictionary, templates
):
    request = _request(
        "Use a prong setting for the center stone.",
        revision,
        active_context,
        dictionary,
        templates,
    )

    result = _process(request, revision, active_context, dictionary, templates)

    assert result.outcome == CorrectionOutcome.APPLIED
    assert result.authoritative_revision.design.center_stone.setting.value == "prong_setting"
    assert (
        result.authoritative_revision.design.center_stone.dimensions
        == revision.design.center_stone.dimensions
    )


def test_locked_field_is_rejected_but_confirmed_unlocked_field_can_be_corrected(
    revision, active_context, dictionary, templates
):
    locked_payload = revision.design.center_stone.shape.model_dump(mode="json")
    locked_payload["locked"] = True
    locked = _revision_with(revision, "center_stone", "shape", value=locked_payload)
    locked_context = _context_for_revision(active_context, locked, templates)
    locked_request = _request(
        "Make the center stone emerald-cut.",
        locked,
        locked_context,
        dictionary,
        templates,
    )

    blocked = _process(locked_request, locked, locked_context, dictionary, templates)

    assert blocked.outcome == CorrectionOutcome.REJECTED
    assert blocked.reason == CorrectionReason.PARSER_REJECTED
    assert blocked.new_revision_id is None
    assert blocked.authoritative_revision.design.center_stone.shape.value == "oval"

    unlocked_request = _request(
        "Make the center stone emerald-cut.",
        revision,
        active_context,
        dictionary,
        templates,
    )
    applied = _process(unlocked_request, revision, active_context, dictionary, templates)
    assert revision.design.center_stone.shape.confirmed is True
    assert applied.authoritative_revision.design.center_stone.shape.confirmed is False
    assert applied.authoritative_revision.design.center_stone.shape.value == "emerald_cut"


def test_prohibition_and_prior_rejection_remain_unaccepted_evidence(
    revision, active_context, dictionary, templates
):
    rejected = _rejected_answer(active_context, revision)
    accepted = _accepted_no_change_answer(active_context, revision)
    request = _request(
        "No halo, please.",
        revision,
        active_context,
        dictionary,
        templates,
    )

    result = _process(
        request,
        revision,
        active_context,
        dictionary,
        templates,
        prior_answer_results=(accepted, rejected),
    )

    assert result.outcome == CorrectionOutcome.DEFERRED
    assert result.reason == CorrectionReason.CONSTRAINT_RETAINED
    assert result.new_revision_id is None
    assert result.prior_answer_results == (accepted, rejected)
    assert result.prior_answer_results[0].outcome == ClarificationAnswerOutcome.NO_CHANGE
    assert result.prior_answer_results[1].outcome == ClarificationAnswerOutcome.REJECTED
    prohibition = next(
        item
        for item in result.parsed_correction.candidates
        if item.classification == CandidateClassification.PROHIBITION
    )
    assert prohibition.subject == CandidateSubject.SETTING
    assert not result.next_enrichment_result.decisions


def test_ambiguous_side_stone_target_never_creates_or_guesses_a_group(
    revision, active_context, dictionary, templates
):
    payload = revision.model_dump(mode="json")
    second = copy.deepcopy(payload["design"]["side_stones"][0])
    second["group_id"] = "accent_pair"
    payload["design"]["side_stones"].append(second)
    multiple = DesignRevision.model_validate(payload)
    context = _context_for_revision(active_context, multiple, templates)
    request = _request(
        "Make the diamonds on the sides emerald-cut.",
        multiple,
        context,
        dictionary,
        templates,
    )

    result = _process(request, multiple, context, dictionary, templates)

    assert result.outcome == CorrectionOutcome.DEFERRED
    assert result.reason == CorrectionReason.AMBIGUOUS_OR_UNRESOLVED
    assert result.new_revision_id is None
    assert tuple(group.group_id for group in result.authoritative_revision.design.side_stones) == (
        "accents",
        "accent_pair",
    )
    assert any(
        item.reason == CandidateDispositionReason.SIDE_STONE_GROUP_AMBIGUOUS
        for item in result.correction_evaluation.dispositions
    )

    no_groups_payload = revision.model_dump(mode="json")
    no_groups_payload["design"]["side_stones"] = []
    no_groups = DesignRevision.model_validate(no_groups_payload)
    no_groups_context = _context_for_revision(active_context, no_groups, templates)
    no_groups_request = _request(
        "Make the diamonds on the sides emerald-cut.",
        no_groups,
        no_groups_context,
        dictionary,
        templates,
    )
    without_group = _process(
        no_groups_request,
        no_groups,
        no_groups_context,
        dictionary,
        templates,
    )
    assert without_group.authoritative_revision.design.side_stones == ()
    assert any(
        item.reason == CandidateDispositionReason.SIDE_STONE_GROUP_MISSING
        for item in without_group.correction_evaluation.dispositions
    )


def test_preservation_and_already_current_corrections_do_not_create_revisions(
    revision, active_context, dictionary, templates
):
    preserve = _request(
        "Keep the center stone exactly as specified.",
        revision,
        active_context,
        dictionary,
        templates,
    )
    preserved = _process(preserve, revision, active_context, dictionary, templates)
    assert preserved.outcome == CorrectionOutcome.NO_CHANGE
    assert preserved.reason == CorrectionReason.PRESERVATION_RETAINED
    assert preserved.new_revision_id is None

    shape = revision.design.center_stone.shape.model_dump(mode="json")
    shape["value"] = "emerald_cut"
    emerald_cut = _revision_with(revision, "center_stone", "shape", value=shape)
    context = _context_for_revision(active_context, emerald_cut, templates)
    repeat = _request(
        "Make the center stone emerald-cut.",
        emerald_cut,
        context,
        dictionary,
        templates,
    )
    repeated = _process(repeat, emerald_cut, context, dictionary, templates)
    assert repeated.outcome == CorrectionOutcome.NO_CHANGE
    assert repeated.reason == CorrectionReason.VALUE_ALREADY_CURRENT
    assert repeated.new_revision_id is None


def test_preference_and_unsupported_wording_are_deferred_without_state_change(
    revision, active_context, dictionary, templates
):
    preference = _request(
        "I would probably prefer yellow gold.",
        revision,
        active_context,
        dictionary,
        templates,
    )
    preferred = _process(preference, revision, active_context, dictionary, templates)
    assert preferred.outcome == CorrectionOutcome.DEFERRED
    assert preferred.reason == CorrectionReason.PREFERENCE_REQUIRES_ACCEPTANCE
    assert preferred.new_revision_id is None

    unsupported = _request(
        "Add an aurora crown around the pavilion.",
        revision,
        active_context,
        dictionary,
        templates,
    )
    deferred = _process(unsupported, revision, active_context, dictionary, templates)
    assert deferred.outcome == CorrectionOutcome.DEFERRED
    assert deferred.new_revision_id is None


@pytest.mark.parametrize(
    ("changes", "override", "code"),
    [
        ({"expected_revision_id": uuid4()}, {}, CorrectionErrorCode.STALE_REVISION),
        ({}, {"authoritative_session_id": uuid4()}, CorrectionErrorCode.CROSS_SESSION),
        (
            {"knowledge_runtime_sha256": "0" * 64},
            {},
            CorrectionErrorCode.RELEASE_MISMATCH,
        ),
        (
            {"dictionary_artifact_version": "9.9.9"},
            {},
            CorrectionErrorCode.ARTIFACT_MISMATCH,
        ),
    ],
)
def test_stale_cross_session_release_and_artifact_mismatches_fail_closed(
    changes,
    override,
    code,
    revision,
    active_context,
    dictionary,
    templates,
):
    request = _request(
        "Make the center stone round.",
        revision,
        active_context,
        dictionary,
        templates,
        **changes,
    )
    with pytest.raises(CorrectionInputError) as error:
        _process(
            request,
            revision,
            active_context,
            dictionary,
            templates,
            **override,
        )
    assert error.value.code == code


def test_exact_evidence_cycle_lineage_and_hash_compatibility_are_preserved(
    revision, active_context, dictionary, templates
):
    text = "  Make the center stone emerald-cut, please.  "
    request = _request(text, revision, active_context, dictionary, templates)
    cycle = active_context[4]
    historical_hash = cycle.result.content_hash

    first = _process(request, revision, active_context, dictionary, templates)
    second = _process(request, revision, active_context, dictionary, templates)

    assert first.parsed_correction.original_text == text
    assert all(
        text[item.evidence.start : item.evidence.end] == item.evidence.text
        for item in first.parsed_correction.candidates
    )
    assert first.previous_enrichment_cycle_id == cycle.enrichment_cycle_id
    assert first.previous_enrichment_content_hash == historical_hash
    assert first.next_enrichment_cycle_number == cycle.cycle_number + 1
    assert first.semantic_hash == second.semantic_hash
    assert first.authoritative_revision.design == second.authoritative_revision.design
    assert first.new_revision_id != second.new_revision_id
    assert cycle.result.content_hash == historical_hash


def test_processing_has_no_persistence_side_effects(
    revision, active_context, dictionary, templates
):
    request = _request(
        "Make the center stone emerald-cut.",
        revision,
        active_context,
        dictionary,
        templates,
    )
    cycle_before = copy.deepcopy(active_context[4])

    result = _process(request, revision, active_context, dictionary, templates)

    assert result.next_enrichment_result.content_hash
    assert active_context[4] == cycle_before
    assert revision.revision_id == active_context[4].specification_revision_id
