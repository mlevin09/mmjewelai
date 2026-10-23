import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jewelai_domain import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ProductionValidationCheck,
    ProductionValidationReport,
    RuntimeProvenance,
    compile_knowledge_library,
    load_domain_dictionary,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_storage import KnowledgeArtifactStore
from jewelai_domain.models import DesignRevision, MessageSource
from jewelai_parser import (
    CandidateClassification,
    CandidateSubject,
    FullMessageParseResult,
    NormalizationSource,
    ParserIssueCode,
    StructuredTarget,
    parse_full_message,
)
from jewelai_prompts import load_prompt_templates

from jewelai_api.parsed_enrichment import (
    CandidateDispositionOutcome,
    CandidateDispositionReason,
    ParsedEnrichmentInputError,
    ParsedEnrichmentReleaseMismatchError,
    ParseKnowledgeLineage,
    enrich_parsed_candidates_with_active_release,
)

ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(ROOT / "data" / "dictionary" / "v1.0.0.json")


@pytest.fixture(scope="module")
def templates():
    return load_prompt_templates(ROOT / "data" / "prompts" / "v1.0.0.json")


@pytest.fixture
def ring():
    return DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))


@pytest.fixture
def active_release(tmp_path):
    payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    payload["domain_knowledge"].extend(
        [
            {
                "concept_id": "stone.material.sapphire",
                "kind": "gemstone_material",
                "relationships": [],
                "claim_ids": [],
                "structural_schema": True,
                "lifecycle_status": "REVIEWED",
            },
            {
                "concept_id": "stone.shape.round",
                "kind": "stone_shape",
                "relationships": [],
                "claim_ids": [],
                "structural_schema": True,
                "lifecycle_status": "REVIEWED",
            },
        ]
    )
    payload["language_mappings"].extend(
        [
            {
                "mapping_id": "LANG-EN-SAPPHIRE",
                "concept_id": "stone.material.sapphire",
                "locale": "en",
                "canonical_term": "sapphire",
                "aliases": [],
                "mapping_mode": "DIRECT",
                "mapping_quality": "EXACT",
                "lifecycle_status": "REVIEWED",
            },
            {
                "mapping_id": "LANG-RU-SAPPHIRE",
                "concept_id": "stone.material.sapphire",
                "locale": "ru",
                "canonical_term": "сапфир",
                "aliases": [],
                "mapping_mode": "DIRECT",
                "mapping_quality": "PREFERRED",
                "lifecycle_status": "REVIEWED",
            },
            {
                "mapping_id": "LANG-EN-ROUND",
                "concept_id": "stone.shape.round",
                "locale": "en",
                "canonical_term": "round",
                "aliases": [],
                "mapping_mode": "DIRECT",
                "mapping_quality": "EXACT",
                "lifecycle_status": "REVIEWED",
            },
            {
                "mapping_id": "LANG-RU-ROUND",
                "concept_id": "stone.shape.round",
                "locale": "ru",
                "canonical_term": "круглый",
                "aliases": [],
                "mapping_mode": "DIRECT",
                "mapping_quality": "PREFERRED",
                "lifecycle_status": "REVIEWED",
            },
        ]
    )
    store = KnowledgeArtifactStore(tmp_path)
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
                evidence_ref=f"ci://parsed-enrichment/{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )
    active = promote_knowledge_runtime(runtime, report)
    return store, stored, runtime, report, active


def _enrich(text, *, locale, revision, dictionary, templates, active_release, runtime=True):
    store, stored, compiled, report, active = active_release
    parsed = parse_full_message(
        text,
        locale=locale,
        dictionary=dictionary,
        knowledge_runtime=compiled if runtime else None,
    )
    result = enrich_parsed_candidates_with_active_release(
        revision,
        parse_result=parsed,
        source=MessageSource(message_id="parsed-message", recorded_at=NOW),
        dictionary=dictionary,
        templates=templates,
        artifact_store=store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
    )
    return parsed, result


def _find(result, *, target=None, classification=None, subject=None, text=None):
    matches = [
        item
        for item in result.dispositions
        if (target is None or item.candidate.target == target)
        and (classification is None or item.candidate.classification == classification)
        and (subject is None or item.candidate.subject == subject)
        and (text is None or item.candidate.evidence.text.casefold() == text.casefold())
    ]
    assert matches, (target, classification, subject, text, result.dispositions)
    return matches[0]


@pytest.mark.parametrize(
    ("locale", "text", "expected_text"),
    [
        (
            "en",
            "Design a platinum ring with an oval center diamond.",
            "platinum",
        ),
        (
            "ru",
            "Создайте кольцо из платины с овальным алмазом в центре.",
            "платины",
        ),
        (
            "ru",
            "Создайте кольцо with a platinum band and oval алмаз в центре.",
            "platinum",
        ),
    ],
)
def test_ru_en_and_mixed_candidates_flow_through_existing_parser_and_matrix(
    locale,
    text,
    expected_text,
    ring,
    dictionary,
    templates,
    active_release,
):
    payload = ring.model_dump(mode="json")
    payload["design"]["metal"]["material"] = None
    revision = DesignRevision.model_validate(payload)
    before = copy.deepcopy(revision)
    _, result = _enrich(
        text,
        locale=locale,
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    platinum = _find(result, target=StructuredTarget.METAL_MATERIAL, text=expected_text)
    assert platinum.outcome == CandidateDispositionOutcome.APPLIED
    assert platinum.enrichment_proposal.provenance == RuntimeProvenance.NORMALIZED_FROM_USER
    assert platinum.enrichment_decision.proposal == platinum.enrichment_proposal
    assert platinum.enrichment_decision.result.value == "platinum"
    center = _find(
        result,
        target=StructuredTarget.CENTER_STONE_MATERIAL,
        subject=CandidateSubject.CENTER_STONE,
    )
    assert center.concrete_target == "center_stone.material"
    assert center.enrichment_proposal is not None
    assert result.enrichment_result.knowledge_runtime_sha256 == active_release[2].sha256
    assert revision == before


def test_constraints_component_roles_and_knowledge_terms_remain_explicit_evidence(
    ring, dictionary, templates, active_release
):
    text = (
        "Make a platinum three-stone ring. Use yellow gold only for the prongs. "
        "No additional stones. Keep the center stone exactly as specified."
    )
    _, result = _enrich(
        text,
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    knowledge_style = _find(result, target=StructuredTarget.STYLE, text="three-stone")
    assert knowledge_style.reason == CandidateDispositionReason.TARGET_NOT_SUPPORTED_BY_PARSER
    assert knowledge_style.enrichment_proposal is None
    for target in (StructuredTarget.METAL_MATERIAL, StructuredTarget.METAL_COLOR):
        prong = _find(result, target=target, subject=CandidateSubject.PRONGS)
        assert prong.reason == CandidateDispositionReason.COMPONENT_TARGET_NOT_REPRESENTABLE
    assert (
        _find(result, classification=CandidateClassification.PROHIBITION).reason
        == CandidateDispositionReason.PROHIBITION_RETAINED
    )
    assert (
        _find(result, classification=CandidateClassification.PRESERVATION).reason
        == CandidateDispositionReason.PRESERVATION_RETAINED
    )


def test_representative_message_preserves_every_fact_and_defers_unsafe_binding(
    ring, dictionary, templates, active_release
):
    payload = ring.model_dump(mode="json")
    payload["design"]["side_stones"] = []
    revision = DesignRevision.model_validate(payload)
    text = (
        "Design a delicate yellow-gold engagement ring with an oval sapphire in the center "
        "and two small round diamonds on the sides. No halo. Keep the center stone unchanged."
    )
    parsed, result = _enrich(
        text,
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    assert result.parse_result == parsed
    assert tuple(item.candidate for item in result.dispositions) == parsed.candidates
    center_sapphire = _find(
        result,
        target=StructuredTarget.CENTER_STONE_MATERIAL,
        subject=CandidateSubject.CENTER_STONE,
        text="sapphire",
    )
    assert center_sapphire.candidate.normalized_values == ("stone.material.sapphire",)
    assert center_sapphire.candidate.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
    assert center_sapphire.reason == CandidateDispositionReason.TARGET_NOT_SUPPORTED_BY_PARSER
    assert _find(result, target=StructuredTarget.CENTER_STONE_SHAPE, text="oval")
    assert (
        _find(result, target=StructuredTarget.SIDE_STONE_QUANTITY).reason
        == CandidateDispositionReason.SIDE_STONE_GROUP_MISSING
    )
    assert (
        _find(result, target=StructuredTarget.SIDE_STONE_SHAPE, text="round").reason
        == CandidateDispositionReason.SIDE_STONE_GROUP_MISSING
    )
    assert (
        _find(result, target=StructuredTarget.SIDE_STONE_MATERIAL, text="diamonds").reason
        == CandidateDispositionReason.SIDE_STONE_GROUP_MISSING
    )
    assert (
        _find(result, classification=CandidateClassification.PROHIBITION).reason
        == CandidateDispositionReason.PROHIBITION_RETAINED
    )
    assert (
        _find(result, classification=CandidateClassification.PRESERVATION).reason
        == CandidateDispositionReason.PRESERVATION_RETAINED
    )
    assert any(
        item.reason == CandidateDispositionReason.UNRESOLVED_CANDIDATE
        and item.candidate.evidence.text.casefold() == "delicate"
        for item in result.dispositions
    )


def test_side_quantity_binds_only_one_existing_stable_group(
    ring, dictionary, templates, active_release
):
    payload = ring.model_dump(mode="json")
    payload["design"]["side_stones"][0]["quantity"]["confirmed"] = False
    revision = DesignRevision.model_validate(payload)
    _, result = _enrich(
        "Add two side diamonds.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    quantity = _find(result, target=StructuredTarget.SIDE_STONE_QUANTITY)
    assert quantity.concrete_target == "side_stones.accents.quantity"
    assert quantity.outcome == CandidateDispositionOutcome.APPLIED
    assert quantity.enrichment_decision.result.value == {"value": 2, "scope": "per_item"}


@pytest.mark.parametrize(
    ("group_count", "reason"),
    [
        (0, CandidateDispositionReason.SIDE_STONE_GROUP_MISSING),
        (2, CandidateDispositionReason.SIDE_STONE_GROUP_AMBIGUOUS),
    ],
)
def test_side_quantity_never_creates_or_guesses_a_group(
    group_count, reason, ring, dictionary, templates, active_release
):
    payload = ring.model_dump(mode="json")
    groups = payload["design"]["side_stones"]
    if group_count == 0:
        payload["design"]["side_stones"] = []
    else:
        second = copy.deepcopy(groups[0])
        second["group_id"] = "other"
        payload["design"]["side_stones"] = [groups[0], second]
    revision = DesignRevision.model_validate(payload)

    _, result = _enrich(
        "Add two side diamonds.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    quantity = _find(result, target=StructuredTarget.SIDE_STONE_QUANTITY)
    assert quantity.reason == reason
    assert quantity.concrete_target is None
    assert quantity.enrichment_proposal is None


def test_preferences_ambiguity_unknowns_and_locked_values_fail_closed(
    ring, dictionary, templates, active_release
):
    _, preference = _enrich(
        "I prefer a platinum ring.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    preferred = _find(preference, target=StructuredTarget.METAL_MATERIAL)
    assert preferred.reason == CandidateDispositionReason.PREFERENCE_REQUIRES_ACCEPTANCE
    assert preferred.enrichment_proposal is None

    _, unresolved = _enrich(
        "Perhaps an oval or emerald-cut center moonstone.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    assert all(
        item.reason == CandidateDispositionReason.AMBIGUOUS_CANDIDATE
        for item in unresolved.dispositions
        if item.candidate.target == StructuredTarget.CENTER_STONE_SHAPE
    )
    assert any(
        item.reason == CandidateDispositionReason.UNRESOLVED_CANDIDATE
        and item.candidate.evidence.text.casefold() == "moonstone"
        for item in unresolved.dispositions
    )

    _, locked = _enrich(
        "Make the ring yellow gold.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    color = _find(locked, target=StructuredTarget.METAL_COLOR)
    assert color.outcome == CandidateDispositionOutcome.BLOCKED
    assert color.parser_issue_codes == (ParserIssueCode.LOCKED_FIELD_CONFLICT,)
    assert color.enrichment_proposal is None


def test_exact_parse_release_is_required_and_absence_is_recorded(
    ring, dictionary, templates, active_release
):
    store, stored, runtime, report, active = active_release
    parsed = parse_full_message(
        "Make a platinum ring.",
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=runtime,
    )
    payload = parsed.model_dump(mode="json")
    payload["knowledge_runtime_sha256"] = "0" * 64
    mismatched = FullMessageParseResult.model_validate(payload)

    with pytest.raises(ParsedEnrichmentReleaseMismatchError, match="does not match"):
        enrich_parsed_candidates_with_active_release(
            ring,
            parse_result=mismatched,
            source=MessageSource(message_id="mismatch", recorded_at=NOW),
            dictionary=dictionary,
            templates=templates,
            artifact_store=store,
            knowledge_package_id=stored.package_id,
            knowledge_artifact_version=stored.artifact_version,
            active_release=active,
            validation_report=report,
        )

    _, without_parse_runtime = _enrich(
        "Make a platinum ring.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
        runtime=False,
    )
    assert without_parse_runtime.parse_knowledge_lineage == ParseKnowledgeLineage.ABSENT


def test_duplicate_candidate_ids_fail_before_evidence_can_be_lost(
    ring, dictionary, templates, active_release
):
    store, stored, runtime, report, active = active_release
    parsed = parse_full_message(
        "Make a platinum ring.",
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=runtime,
    )
    payload = parsed.model_dump(mode="json")
    payload["candidates"][1]["candidate_id"] = payload["candidates"][0]["candidate_id"]
    duplicated = FullMessageParseResult.model_validate(payload)

    with pytest.raises(ParsedEnrichmentInputError, match="must be unique"):
        enrich_parsed_candidates_with_active_release(
            ring,
            parse_result=duplicated,
            source=MessageSource(message_id="duplicate", recorded_at=NOW),
            dictionary=dictionary,
            templates=templates,
            artifact_store=store,
            knowledge_package_id=stored.package_id,
            knowledge_artifact_version=stored.artifact_version,
            active_release=active,
            validation_report=report,
        )


def test_explicit_release_never_falls_forward_and_result_is_deterministic(
    ring, dictionary, templates, active_release
):
    store, stored, runtime, report, active = active_release
    second_payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    second_payload["artifact_version"] = "1.1.0"
    store.publish(second_payload)

    first_parse, first = _enrich(
        "Make a platinum ring.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=(store, stored, runtime, report, active),
    )
    _, second = _enrich(
        "Make a platinum ring.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=(store, stored, runtime, report, active),
    )

    assert first == second
    assert first.parse_result == first_parse
    assert first.enrichment_result.knowledge_artifact_version == "1.0.0"
    assert all(
        proposal.provenance != RuntimeProvenance.JEWELAI_RECOMMENDED
        for proposal in (
            item.enrichment_proposal
            for item in first.dispositions
            if item.enrichment_proposal is not None
        )
    )
