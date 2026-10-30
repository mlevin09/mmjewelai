import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from jewelai_domain import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ProductionValidationCheck,
    ProductionValidationReport,
    RuntimeProvenance,
    RuntimeSemanticState,
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
from jewelai_prompts import (
    CanonicalInternalFinalPromptV2_1 as InternalFinalPrompt,
)
from jewelai_prompts import (
    EnrichmentProposal,
    FinalPromptArtifactVersions,
    FinalPromptSnapshot,
    KnowledgeReleaseReference,
    assemble_internal_final_prompt,
    enrich_prompt_with_active_release,
    load_prompt_templates,
)

from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.clarification import (
    ClarificationCategory,
    ClarificationImportance,
    ClarificationPlanInputError,
    UnaskedReason,
    plan_clarifications,
)
from jewelai_api.clarification_answers import (
    ClarificationAnswer,
    ClarificationAnswerError,
    ClarificationAnswerErrorCode,
    ClarificationAnswerOutcome,
    ClarificationAnswerReason,
    ClarificationDecision,
    process_clarification_answer,
)
from jewelai_api.constraint_evidence import merge_constraint_evidence
from jewelai_api.parsed_enrichment import (
    CandidateDispositionOutcome,
    CandidateDispositionReason,
    ParsedEnrichmentInputError,
    ParsedEnrichmentReleaseMismatchError,
    ParseKnowledgeLineage,
    enrich_parsed_candidates_with_active_release,
)
from jewelai_api.settings import ArtifactVersions

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


@pytest.fixture(scope="module")
def runtime_artifacts():
    return load_runtime_artifacts(ROOT, ArtifactVersions())


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
    return _publish_test_release(tmp_path, payload)


def _publish_test_release(tmp_path, payload):
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


@pytest.fixture
def collision_release(tmp_path, dictionary):
    # Synthetic, disposable validation release; never activate the real catalog.
    payload = json.loads(KNOWLEDGE.read_text(encoding="utf-8"))
    for domain_id, kind in (
        ("gold", "metal_material"),
        ("platinum", "metal_material"),
        ("ring", "jewelry_type"),
        ("oval", "stone_shape"),
        ("diamond", "gemstone_material"),
    ):
        payload["domain_knowledge"].append(
            {
                "concept_id": domain_id,
                "kind": kind,
                "relationships": [],
                "claim_ids": [],
                "structural_schema": True,
                "lifecycle_status": "REVIEWED",
            }
        )
        entry = dictionary[domain_id]
        for locale in ("en", "ru"):
            payload["language_mappings"].append(
                {
                    "mapping_id": f"LANG-COLLISION-{domain_id.upper()}-{locale.upper()}",
                    "concept_id": domain_id,
                    "locale": locale,
                    "canonical_term": getattr(entry.canonical_terms, locale),
                    "aliases": list(getattr(entry.synonyms, locale)),
                    "mapping_mode": "DIRECT",
                    "mapping_quality": "EXACT",
                    "lifecycle_status": "REVIEWED",
                }
            )
    return _publish_test_release(tmp_path, payload)


@pytest.mark.parametrize(
    ("locale", "text"),
    [
        ("en", "Gold ring with an oval diamond"),
        ("ru", "Кольцо из золота с овальным алмазом."),
        ("ru", "Кольцо with gold and an oval алмаз."),
    ],
)
def test_overlap_preserves_actual_parser_and_matrix_updates(
    locale, text, ring, dictionary, templates, collision_release
):
    payload = ring.model_dump(mode="json")
    payload["design"] = {}
    revision = DesignRevision.model_validate(payload)
    before = revision.model_dump_json()
    results = [
        _enrich(
            text,
            locale=locale,
            revision=revision,
            dictionary=dictionary,
            templates=templates,
            active_release=collision_release,
            runtime=enabled,
        )[1]
        for enabled in (False, True)
    ]
    baseline, combined = results
    assert combined.parser_proposal.accepted_updates == baseline.parser_proposal.accepted_updates
    assert len(combined.parser_proposal.accepted_updates) == 4
    # Added evidence legitimately renumbers candidates; semantic state and its
    # provenance must match, while each new source ID must bind its own evidence.
    assert tuple(
        cell.model_dump(exclude={"source_ids"}) for cell in combined.enrichment_result.final_matrix
    ) == tuple(
        cell.model_dump(exclude={"source_ids"}) for cell in baseline.enrichment_result.final_matrix
    )
    assert not combined.parser_proposal.issues
    assert (
        tuple(item.candidate for item in combined.dispositions) == combined.parse_result.candidates
    )
    assert all(
        item.reason != CandidateDispositionReason.DUPLICATE_TARGET_CANDIDATES
        for item in combined.dispositions
    )
    for disposition in combined.dispositions:
        if disposition.candidate.normalization_source == NormalizationSource.DOMAIN_DICTIONARY:
            assert disposition.outcome == CandidateDispositionOutcome.APPLIED
            assert (
                disposition.enrichment_proposal.provenance == RuntimeProvenance.NORMALIZED_FROM_USER
            )
            assert disposition.enrichment_proposal.source_id == disposition.candidate.candidate_id
        elif disposition.candidate.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY:
            assert disposition.reason == CandidateDispositionReason.TARGET_NOT_SUPPORTED_BY_PARSER
            assert disposition.enrichment_proposal is None
    assert revision.model_dump_json() == before
    assert (
        combined
        == _enrich(
            text,
            locale=locale,
            revision=revision,
            dictionary=dictionary,
            templates=templates,
            active_release=collision_release,
        )[1]
    )


@pytest.mark.parametrize("text", ("Gold and platinum ring.", "Gold gold ring."))
def test_overlap_does_not_resolve_existing_multi_target_conflicts(
    text, ring, dictionary, templates, collision_release
):
    for enabled in (False, True):
        _, result = _enrich(
            text,
            locale="en",
            revision=ring,
            dictionary=dictionary,
            templates=templates,
            active_release=collision_release,
            runtime=enabled,
        )
        metal = [
            item
            for item in result.dispositions
            if item.candidate.target == StructuredTarget.METAL_MATERIAL
            and item.candidate.normalization_source == NormalizationSource.DOMAIN_DICTIONARY
        ]
        assert len(metal) == 2
        assert all(
            item.reason == CandidateDispositionReason.DUPLICATE_TARGET_CANDIDATES for item in metal
        )
        assert all(item.enrichment_proposal is None for item in metal)


def test_overlap_preserves_locked_field_conflicts(ring, dictionary, templates, collision_release):
    payload = ring.model_dump(mode="json")
    payload["design"]["metal"]["material"]["locked"] = True
    revision = DesignRevision.model_validate(payload)
    for enabled in (False, True):
        _, result = _enrich(
            "Platinum ring.",
            locale="en",
            revision=revision,
            dictionary=dictionary,
            templates=templates,
            active_release=collision_release,
            runtime=enabled,
        )
        metal = next(
            item
            for item in result.dispositions
            if item.candidate.target == StructuredTarget.METAL_MATERIAL
            and item.candidate.normalization_source == NormalizationSource.DOMAIN_DICTIONARY
        )
        assert metal.outcome == CandidateDispositionOutcome.BLOCKED
        assert metal.parser_issue_codes == (ParserIssueCode.LOCKED_FIELD_CONFLICT,)
        assert revision.design.metal.material.value == "gold"
        assert revision.design.metal.material.locked


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
    ("locale", "text", "halo_kind", "halo_wording", "update_count", "knowledge_count"),
    [
        ("en", "Gold ring with an oval diamond.", None, None, 4, 4),
        (
            "en",
            "Gold ring with an oval diamond. Do not add a halo.",
            "prohibition",
            "Do not add a halo",
            4,
            4,
        ),
        (
            "ru",
            "Кольцо из золота с овальным алмазом. Не добавляйте гало.",
            "prohibition",
            "Не добавляйте гало",
            4,
            3,  # This synthetic Knowledge fixture lacks the inflected gold surface.
        ),
        (
            "ru",
            "Хочу gold ring with an oval diamond. Do not add гало.",
            "prohibition",
            "Do not add гало",
            0,
            4,
        ),
        (
            "en",
            "Gold ring with an oval diamond. Actually, add a halo.",
            "requirement",
            "add a halo",
            4,
            4,
        ),
    ],
)
def test_combined_collision_and_halo_preserve_matrix_and_final_constraints(
    locale,
    text,
    halo_kind,
    halo_wording,
    update_count,
    knowledge_count,
    ring,
    dictionary,
    templates,
    collision_release,
    runtime_artifacts,
):
    revision = ring.model_copy(update={"design": type(ring.design)()})
    before = revision.model_dump_json()
    session_id, organization_id, cycle_id = uuid4(), uuid4(), uuid4()
    matrices, instructions, dictionary_evidence = [], [], []
    for enabled in (False, True):
        parsed, result = _enrich(
            text,
            locale=locale,
            revision=revision,
            dictionary=dictionary,
            templates=templates,
            active_release=collision_release,
            runtime=enabled,
        )
        assert (
            parsed
            == _enrich(
                text,
                locale=locale,
                revision=revision,
                dictionary=dictionary,
                templates=templates,
                active_release=collision_release,
                runtime=enabled,
            )[0]
        )
        dictionary_candidates = [
            item
            for item in parsed.candidates
            if item.normalization_source == NormalizationSource.DOMAIN_DICTIONARY
        ]
        knowledge_candidates = [
            item
            for item in parsed.candidates
            if item.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
        ]
        assert len(dictionary_candidates) == 4
        assert len(knowledge_candidates) == (knowledge_count if enabled else 0)
        dictionary_evidence.append(
            [item.model_dump(exclude={"candidate_id"}) for item in dictionary_candidates]
        )
        assert len(result.parser_proposal.accepted_updates) == update_count
        assert all(item.parser_update is None for item in knowledge_candidates)
        for disposition in result.dispositions:
            if disposition.candidate in knowledge_candidates:
                assert disposition.enrichment_proposal is None
            if disposition.enrichment_proposal is not None:
                assert disposition.candidate in dictionary_candidates
                assert (
                    disposition.enrichment_proposal.source_id == disposition.candidate.candidate_id
                )
                assert (
                    disposition.enrichment_proposal.provenance
                    == RuntimeProvenance.NORMALIZED_FROM_USER
                )
        if update_count == 0:
            # "Хочу" marks preferences, not accepted requirements; adding Knowledge
            # must not grant those preferences authority or invent a missing binding.
            assert all(
                item.classification == CandidateClassification.PREFERENCE
                for item in dictionary_candidates
            )
        for candidate in parsed.candidates:
            assert (
                text[candidate.evidence.start : candidate.evidence.end] == candidate.evidence.text
            )
        halo = [item for item in parsed.candidates if item.semantic_subject == "feature.halo"]
        assert len(halo) == (1 if halo_kind else 0)
        if halo:
            assert halo[0].classification.value == halo_kind
            assert halo[0].evidence.text == halo_wording
            assert halo[0].parser_update is None
        matrices.append(
            [
                cell.model_dump(exclude={"source_ids"})
                for cell in result.enrichment_result.final_matrix
            ]
        )
        evidence = merge_constraint_evidence(
            result,
            session_id=session_id,
            organization_id=organization_id,
            source=result.parser_proposal.source,
            authoritative_revision=revision,
            enrichment_cycle_id=cycle_id,
        )
        snapshot = FinalPromptSnapshot(
            session_id=session_id,
            organization_id=organization_id,
            locale=locale,
            revision=revision,
            enrichment_cycle_id=cycle_id,
            latest_enrichment_cycle_id=cycle_id,
            enrichment_cycle_number=1,
            enrichment_result=result.enrichment_result,
            knowledge_release=KnowledgeReleaseReference(
                package_id=collision_release[4].package_id,
                artifact_version=collision_release[4].artifact_version,
                runtime_sha256=collision_release[4].runtime_sha256,
                validation_report_sha256=collision_release[4].validation_report_sha256,
            ),
            artifact_versions=FinalPromptArtifactVersions(
                design_schema_version=revision.schema_version,
                dictionary_artifact_version=dictionary.artifact_version,
                question_artifact_version=runtime_artifacts.questions.artifact_version,
                rules_artifact_version=runtime_artifacts.rules.artifact_version,
                prompt_template_artifact_version=templates.artifact_version,
                enrichment_version=result.enrichment_result.enrichment_version,
            ),
            rule_decision=runtime_artifacts.rules.evaluate(revision, "retail_client"),
            constraint_evidence=evidence,
        )
        final = assemble_internal_final_prompt(
            snapshot, dictionary=dictionary, templates=templates
        ).internal_final_prompt
        assert InternalFinalPrompt.model_validate_json(final.model_dump_json()) == final
        final_halo = [item for item in final.constraints if item.target == "feature.halo"]
        assert len(final_halo) == (1 if halo_kind else 0)
        if final_halo:
            assert final_halo[0].kind == halo_kind
        instructions.append([item.model_dump() for item in final_halo])
    assert dictionary_evidence[0] == dictionary_evidence[1]
    assert matrices[0] == matrices[1]
    # Source IDs legitimately differ with added evidence; compare semantic instructions.
    assert [(item["kind"], item["instruction"]) for item in instructions[0]] == [
        (item["kind"], item["instruction"]) for item in instructions[1]
    ]
    assert revision.model_dump_json() == before


@pytest.mark.parametrize("role_id", ("retail_client", "jewelry_designer"))
def test_combined_four_turn_halo_history_uses_collision_release(
    engine, tmp_path, monkeypatch, role_id, collision_release
):
    from conftest import NOW as API_NOW
    from test_prompt_enrichment_integration import _exercise_halo_constraint_sequence

    from jewelai_api.prompt_enrichment_runtime import PromptEnrichmentRuntimeService

    store, stored, _, report, active = collision_release
    from jewelai_domain.knowledge_activation_v1_1 import (
        ProductionValidationReportV1_1,
        promote_knowledge_runtime_v1_1,
    )
    from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1
    from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1

    payload = json.loads((Path(stored.release_path) / "source.json").read_text())
    payload["contract_version"] = "1.1.0"
    store = KnowledgeArtifactStoreV1_1(tmp_path / "session-collision-v1-1")
    stored = store.publish(payload)
    compiled, _ = compile_knowledge_library_v1_1(payload)
    report = ProductionValidationReportV1_1(
        package_id=compiled.package_id,
        artifact_version=compiled.artifact_version,
        runtime_sha256=compiled.sha256,
        checks=report.checks,
    )
    active = promote_knowledge_runtime_v1_1(compiled, report)

    def runtime_factory(service, _tmp_path):
        runtime = PromptEnrichmentRuntimeService(
            service.repository,
            service.artifacts,
            store,
            knowledge_package_id=stored.package_id,
            knowledge_artifact_version=stored.artifact_version,
            active_release=active,
            validation_report=report,
            clock=lambda: API_NOW,
            uuid_factory=uuid4,
        )
        return runtime, store, active, report

    monkeypatch.setattr("test_prompt_enrichment_integration._runtime", runtime_factory)
    trace = _exercise_halo_constraint_sequence(
        engine,
        tmp_path,
        role_id,
        "en",
        (
            (
                "Gold engagement ring with an oval diamond. No halo.",
                "prohibition",
                "No halo",
            ),
            (
                "Keep the oval center stone. Do not add a halo.",
                "prohibition",
                "Do not add a halo",
            ),
            ("Actually, add a halo.", "requirement", "add a halo"),
            ("I changed my mind. Don't include a halo.", "prohibition", "Don't include a halo"),
        ),
        initial_center_fields=("shape", "material"),
    )
    for turn in trace["turns"]:
        revision = DesignRevision.model_validate(turn["revision"])
        assert revision.design.metal.material.value == "gold"
        assert revision.design.center_stone.shape.value == "oval"
        assert revision.design.center_stone.material.value == "diamond"
        assert revision.design.center_stone.dimensions.locked
    initial = FullMessageParseResult.model_validate(trace["turns"][0]["parse_result"])
    assert (
        len(
            [
                item
                for item in initial.candidates
                if item.normalization_source == NormalizationSource.KNOWLEDGE_LIBRARY
            ]
        )
        >= 4
    )
    assert UUID(trace["session_id"])


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


def _plan(revision, enrichment, runtime_artifacts, *, role_id="retail_client"):
    return plan_clarifications(
        revision,
        enrichment,
        role_id=role_id,
        dictionary=runtime_artifacts.dictionary,
        questions=runtime_artifacts.questions,
        rules=runtime_artifacts.rules,
    )


@pytest.mark.parametrize(
    ("locale", "text", "expected_fragment"),
    [
        (
            "en",
            "Design a platinum ring with either an oval or emerald-cut center diamond.",
            "Which option would you prefer",
        ),
        (
            "ru",
            "Создайте кольцо с овальным или emerald-cut центральным бриллиантом.",
            "Какой вариант вы предпочитаете",
        ),
        (
            "en",
            "Create ring с овальным or emerald-cut center diamond.",
            "Which option would you prefer",
        ),
    ],
)
def test_clarification_planner_localizes_one_verified_material_choice(
    locale,
    text,
    expected_fragment,
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    payload = ring.model_dump(mode="json")
    payload["design"]["center_stone"]["shape"] = None
    revision = DesignRevision.model_validate(payload)
    _, enriched = _enrich(
        text,
        locale=locale,
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    first = _plan(revision, enriched, runtime_artifacts)
    second = _plan(revision, enriched, runtime_artifacts)

    ambiguity = next(
        item
        for item in first.questions
        if item.category == ClarificationCategory.MATERIAL_AMBIGUITY
    )
    assert first == second
    assert first.content_hash == second.content_hash
    assert ambiguity.importance == ClarificationImportance.BLOCKING
    assert expected_fragment in ambiguity.text
    assert {item.value for item in ambiguity.options} == {"oval", "emerald_cut"}
    assert tuple(item.candidate_id for item in ambiguity.evidence) == (
        ambiguity.source_candidate_ids
    )
    for evidence in ambiguity.evidence:
        assert enriched.parse_result.original_text[evidence.start : evidence.end] == evidence.text
    assert ambiguity.design_revision_id == str(revision.revision_id)
    assert ambiguity.knowledge_runtime_sha256 == active_release[2].sha256
    assert (
        ambiguity.knowledge_validation_report_sha256 == active_release[4].validation_report_sha256
    )
    assert "center_stone.shape" not in ambiguity.text
    assert "group_id" not in ambiguity.text
    assert active_release[2].sha256 not in ambiguity.text


def test_preference_is_optional_but_approved_missing_information_is_blocking(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    payload = ring.model_dump(mode="json")
    payload["design"]["metal"]["color"] = None
    revision = DesignRevision.model_validate(payload)
    _, enriched = _enrich(
        "I would probably prefer a delicate yellow-gold ring.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    plan = _plan(revision, enriched, runtime_artifacts)
    preference = next(
        item
        for item in plan.questions
        if item.category == ClarificationCategory.PREFERENCE_ACCEPTANCE
    )
    blocking = tuple(
        item for item in plan.questions if item.importance == ClarificationImportance.BLOCKING
    )

    assert preference.importance == ClarificationImportance.OPTIONAL
    assert tuple(item.value for item in preference.options) == ("yellow",)
    assert "Would you like" in preference.text
    assert blocking
    assert all(item.rule_id is not None for item in blocking)
    assert plan.can_continue_without_answers is False
    delicate = next(
        item
        for item in enriched.dispositions
        if item.candidate.evidence.text.casefold() == "delicate"
    )
    assert any(
        item.candidate_id == delicate.candidate.candidate_id
        and item.reason == UnaskedReason.NONCRITICAL_UNKNOWN
        for item in plan.unasked_evidence
    )


def test_unsupported_side_group_negative_and_preservation_evidence_do_not_create_questions(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    payload = ring.model_dump(mode="json")
    second = copy.deepcopy(payload["design"]["side_stones"][0])
    second["group_id"] = "other"
    payload["design"]["side_stones"].append(second)
    revision = DesignRevision.model_validate(payload)
    _, enriched = _enrich(
        "Make the diamonds on the sides round. No halo. "
        "Keep the center stone exactly as specified.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    plan = _plan(revision, enriched, runtime_artifacts)
    side_ids = {
        item.candidate.candidate_id
        for item in enriched.dispositions
        if item.candidate.subject == CandidateSubject.SIDE_STONES
    }
    assert side_ids
    assert not any(side_ids.intersection(item.source_candidate_ids) for item in plan.questions)
    assert all(
        any(entry.candidate_id == candidate_id for entry in plan.unasked_evidence)
        for candidate_id in side_ids
    )
    assert {item.reason for item in plan.unasked_evidence} >= {
        UnaskedReason.UNSUPPORTED_ANSWER_PATH,
        UnaskedReason.CONSTRAINT_RETAINED,
    }


def test_confirmed_and_locked_targets_are_never_offered_for_replacement(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    _, enriched = _enrich(
        "Perhaps an oval or emerald-cut center diamond. I prefer yellow gold.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    plan = _plan(ring, enriched, runtime_artifacts)
    protected = {
        item.candidate_id
        for item in plan.unasked_evidence
        if item.reason == UnaskedReason.TARGET_ALREADY_CONFIRMED
    }
    expected = {
        item.candidate.candidate_id
        for item in enriched.dispositions
        if item.candidate.target
        in {StructuredTarget.CENTER_STONE_SHAPE, StructuredTarget.METAL_COLOR}
        and item.reason
        in {
            CandidateDispositionReason.AMBIGUOUS_CANDIDATE,
            CandidateDispositionReason.PREFERENCE_REQUIRES_ACCEPTANCE,
        }
    }
    assert protected == expected
    assert not any(expected.intersection(item.source_candidate_ids) for item in plan.questions)


def test_knowledge_recommendation_requires_acceptance_without_mutating_product_state(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    payload = ring.model_dump(mode="json")
    payload["design"]["metal"]["color"] = None
    revision = DesignRevision.model_validate(payload)
    before = copy.deepcopy(revision)
    _, enriched = _enrich(
        "Create a ring.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    store, stored, _, report, active = active_release
    recommendation = enrich_prompt_with_active_release(
        revision,
        templates,
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        proposals=(
            EnrichmentProposal(
                target="metal.color",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="yellow",
                source_id="DEC-THREE-STONE-POLICY",
            ),
        ),
    )
    enriched_payload = enriched.model_dump(mode="json")
    enriched_payload["enrichment_result"] = recommendation.model_dump(mode="json")
    enriched_with_recommendation = type(enriched).model_validate(enriched_payload)

    plan = _plan(revision, enriched_with_recommendation, runtime_artifacts)
    question = next(
        item
        for item in plan.questions
        if item.category == ClarificationCategory.KNOWLEDGE_RECOMMENDATION
    )

    assert question.importance == ClarificationImportance.RECOMMENDED
    assert question.source_proposal_ids == ("DEC-THREE-STONE-POLICY",)
    assert tuple(item.value for item in question.options) == ("yellow",)
    assert revision == before
    assert revision.design.metal.color is None


def test_empty_plan_is_valid_for_noncritical_unknowns_when_rules_are_ready(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    payload = ring.model_dump(mode="json")
    source = copy.deepcopy(payload["design"]["center_stone"]["weight"])
    source["value"] = {
        "length": {"value": 9.0, "unit": "mm"},
        "width": {"value": 7.0, "unit": "mm"},
        "depth": {"value": 4.5, "unit": "mm"},
    }
    payload["design"]["center_stone"]["dimensions"] = source
    setting = copy.deepcopy(payload["design"]["center_stone"]["shape"])
    setting["value"] = "prong"
    payload["design"]["center_stone"]["setting"] = setting
    revision = DesignRevision.model_validate(payload)
    _, enriched = _enrich(
        "Make it delicate.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )

    plan = _plan(revision, enriched, runtime_artifacts)

    assert plan.questions == ()
    assert plan.can_continue_without_answers is True
    assert plan.unasked_evidence
    assert all(item.reason == UnaskedReason.NONCRITICAL_UNKNOWN for item in plan.unasked_evidence)


def test_clarification_planner_rejects_mismatched_release_lineage(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    _, enriched = _enrich(
        "Create a platinum ring.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    payload = enriched.model_dump(mode="json")
    payload["parse_result"]["knowledge_runtime_sha256"] = "0" * 64
    mismatched = type(enriched).model_validate(payload)

    with pytest.raises(ClarificationPlanInputError, match="identities do not match"):
        _plan(ring, mismatched, runtime_artifacts)


def _answer(plan, question, *, session_id, decision, selected_option=None, **changes):
    payload = {
        "session_id": session_id,
        "plan_content_hash": plan.content_hash,
        "clarification_id": question.clarification_id,
        "decision": decision,
        "selected_option": selected_option,
        "expected_revision_id": plan.design_revision_id,
        "knowledge_package_id": plan.knowledge_package_id,
        "knowledge_artifact_version": plan.knowledge_artifact_version,
        "knowledge_runtime_sha256": plan.knowledge_runtime_sha256,
        "knowledge_validation_report_sha256": plan.knowledge_validation_report_sha256,
        "source": MessageSource(message_id="clarification-answer", recorded_at=NOW),
    }
    payload.update(changes)
    return ClarificationAnswer.model_validate(payload)


def _process(plan, answer, revision, active_release, runtime_artifacts, **changes):
    options = {
        "authoritative_session_id": answer.session_id,
        "current_revision": revision,
        "active_release": active_release[4],
        "dictionary": runtime_artifacts.dictionary,
        "questions": runtime_artifacts.questions,
        "rules": runtime_artifacts.rules,
        "created_at": NOW,
    }
    options.update(changes)
    return process_clarification_answer(plan, answer, **options)


def _ambiguous_shape_plan(ring, dictionary, templates, active_release, runtime_artifacts):
    payload = ring.model_dump(mode="json")
    payload["design"]["center_stone"]["shape"] = None
    revision = DesignRevision.model_validate(payload)
    _, enriched = _enrich(
        "Design a platinum ring with either an oval or emerald-cut center diamond.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    plan = _plan(revision, enriched, runtime_artifacts)
    question = next(
        item for item in plan.questions if item.category == ClarificationCategory.MATERIAL_AMBIGUITY
    )
    return revision, plan, question


def _preference_plan(ring, dictionary, templates, active_release, runtime_artifacts):
    payload = ring.model_dump(mode="json")
    payload["design"]["metal"]["color"] = None
    revision = DesignRevision.model_validate(payload)
    _, enriched = _enrich(
        "I would probably prefer a delicate yellow-gold ring.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    plan = _plan(revision, enriched, runtime_artifacts)
    question = next(
        item
        for item in plan.questions
        if item.category == ClarificationCategory.PREFERENCE_ACCEPTANCE
    )
    return revision, plan, question


def _recommendation_plan(ring, dictionary, templates, active_release, runtime_artifacts):
    revision, _, _ = _preference_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    _, enriched = _enrich(
        "Create a ring.",
        locale="en",
        revision=revision,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    store, stored, _, report, active = active_release
    recommendation = enrich_prompt_with_active_release(
        revision,
        templates,
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        proposals=(
            EnrichmentProposal(
                target="metal.color",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="yellow",
                source_id="DEC-THREE-STONE-POLICY",
            ),
        ),
    )
    payload = enriched.model_dump(mode="json")
    payload["enrichment_result"] = recommendation.model_dump(mode="json")
    enriched = type(enriched).model_validate(payload)
    plan = _plan(revision, enriched, runtime_artifacts)
    question = next(
        item
        for item in plan.questions
        if item.category == ClarificationCategory.KNOWLEDGE_RECOMMENDATION
    )
    return revision, plan, question


def test_answer_selects_only_an_offered_shape_and_preserves_unrelated_state(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _ambiguous_shape_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    session_id = uuid4()
    answer = _answer(
        plan,
        question,
        session_id=session_id,
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option="emerald_cut",
    )

    result = _process(plan, answer, revision, active_release, runtime_artifacts)

    assert result.outcome == ClarificationAnswerOutcome.APPLIED
    assert result.reason == ClarificationAnswerReason.USER_SELECTED_OFFERED_OPTION
    assert result.resulting_revision.design.center_stone.shape.value == "emerald_cut"
    assert result.resulting_revision.design.center_stone.shape.source == answer.source
    assert result.resulting_revision.design.metal == revision.design.metal
    assert result.resulting_revision.design.side_stones == revision.design.side_stones
    assert result.previous_revision_id == revision.revision_id
    assert result.new_revision_id == result.resulting_revision.revision_id
    assert result.source_candidate_ids == question.source_candidate_ids
    assert result.evidence == question.evidence
    assert result.knowledge_runtime_sha256 == plan.knowledge_runtime_sha256


def test_answer_application_does_not_create_a_missing_side_stone_group(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    payload = ring.model_dump(mode="json")
    payload["design"]["side_stones"] = []
    without_side_stones = DesignRevision.model_validate(payload)
    revision, plan, question = _ambiguous_shape_plan(
        without_side_stones,
        dictionary,
        templates,
        active_release,
        runtime_artifacts,
    )
    answer = _answer(
        plan,
        question,
        session_id=uuid4(),
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option="oval",
    )

    result = _process(plan, answer, revision, active_release, runtime_artifacts)

    assert result.outcome == ClarificationAnswerOutcome.APPLIED
    assert revision.design.side_stones == ()
    assert result.resulting_revision.design.side_stones == ()


def test_explicit_preference_acceptance_applies_only_the_recorded_option(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _preference_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    answer = _answer(
        plan,
        question,
        session_id=uuid4(),
        decision=ClarificationDecision.ACCEPT,
    )

    result = _process(plan, answer, revision, active_release, runtime_artifacts)

    assert result.outcome == ClarificationAnswerOutcome.APPLIED
    assert result.reason == ClarificationAnswerReason.USER_ACCEPTED_PREFERENCE
    assert result.selected_option.value == "yellow"
    assert result.resulting_revision.design.metal.color.value == "yellow"
    assert result.resulting_revision.design.center_stone == revision.design.center_stone


@pytest.mark.parametrize(
    ("decision", "outcome", "reason", "resolved"),
    [
        (
            ClarificationDecision.REJECT,
            ClarificationAnswerOutcome.REJECTED,
            ClarificationAnswerReason.USER_REJECTED_OFFER,
            True,
        ),
        (
            ClarificationDecision.SKIP,
            ClarificationAnswerOutcome.SKIPPED,
            ClarificationAnswerReason.USER_SKIPPED,
            False,
        ),
        (
            ClarificationDecision.UNKNOWN,
            ClarificationAnswerOutcome.UNKNOWN,
            ClarificationAnswerReason.USER_DOES_NOT_KNOW,
            False,
        ),
    ],
)
def test_reject_skip_and_unknown_preserve_state_without_implicit_acceptance(
    decision,
    outcome,
    reason,
    resolved,
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _recommendation_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    answer = _answer(plan, question, session_id=uuid4(), decision=decision)

    first = _process(plan, answer, revision, active_release, runtime_artifacts)
    second = _process(plan, answer, revision, active_release, runtime_artifacts)

    assert first == second
    assert first.outcome == outcome
    assert first.reason == reason
    assert first.question_resolved is resolved
    assert first.blocks_progression is False
    assert first.new_revision_id is None
    assert first.resulting_revision is None
    assert revision.design.metal.color is None
    assert first.source_proposal_ids == ("DEC-THREE-STONE-POLICY",)


def test_knowledge_recommendation_requires_explicit_acceptance_to_apply(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _recommendation_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    answer = _answer(
        plan,
        question,
        session_id=uuid4(),
        decision=ClarificationDecision.ACCEPT,
    )

    result = _process(plan, answer, revision, active_release, runtime_artifacts)

    assert result.outcome == ClarificationAnswerOutcome.APPLIED
    assert result.reason == ClarificationAnswerReason.USER_ACCEPTED_RECOMMENDATION
    assert result.resulting_revision.design.metal.color.value == "yellow"
    assert result.source_proposal_ids == ("DEC-THREE-STONE-POLICY",)


def test_skip_or_unknown_does_not_resolve_a_blocking_question(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _ambiguous_shape_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    assert question.importance == ClarificationImportance.BLOCKING

    for decision in (ClarificationDecision.SKIP, ClarificationDecision.UNKNOWN):
        answer = _answer(plan, question, session_id=uuid4(), decision=decision)
        result = _process(plan, answer, revision, active_release, runtime_artifacts)
        assert result.question_resolved is False
        assert result.blocks_progression is True
        assert result.new_revision_id is None


def test_invalid_option_unknown_question_and_cross_session_fail_closed(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _ambiguous_shape_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    session_id = uuid4()
    invalid = _answer(
        plan,
        question,
        session_id=session_id,
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option="round",
    )
    with pytest.raises(ClarificationAnswerError) as invalid_error:
        _process(plan, invalid, revision, active_release, runtime_artifacts)
    assert invalid_error.value.code == ClarificationAnswerErrorCode.INVALID_OPTION

    unknown = invalid.model_copy(
        update={"clarification_id": "clarification_does_not_exist", "selected_option": "oval"}
    )
    with pytest.raises(ClarificationAnswerError) as unknown_error:
        _process(plan, unknown, revision, active_release, runtime_artifacts)
    assert unknown_error.value.code == ClarificationAnswerErrorCode.UNKNOWN_QUESTION

    valid = invalid.model_copy(update={"selected_option": "oval"})
    with pytest.raises(ClarificationAnswerError) as scope_error:
        _process(
            plan,
            valid,
            revision,
            active_release,
            runtime_artifacts,
            authoritative_session_id=uuid4(),
        )
    assert scope_error.value.code == ClarificationAnswerErrorCode.CROSS_SESSION


def test_tampered_plan_stale_revision_and_release_mismatch_fail_closed(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _ambiguous_shape_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    answer = _answer(
        plan,
        question,
        session_id=uuid4(),
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option="oval",
    )

    tampered = plan.model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(ClarificationAnswerError) as plan_error:
        _process(tampered, answer, revision, active_release, runtime_artifacts)
    assert plan_error.value.code == ClarificationAnswerErrorCode.INVALID_PLAN

    stale_payload = revision.model_dump(mode="json")
    stale_payload["revision_id"] = str(uuid4())
    stale = DesignRevision.model_validate(stale_payload)
    with pytest.raises(ClarificationAnswerError) as stale_error:
        _process(plan, answer, stale, active_release, runtime_artifacts)
    assert stale_error.value.code == ClarificationAnswerErrorCode.STALE_REVISION

    mismatched = answer.model_copy(update={"knowledge_runtime_sha256": "0" * 64})
    with pytest.raises(ClarificationAnswerError) as release_error:
        _process(plan, mismatched, revision, active_release, runtime_artifacts)
    assert release_error.value.code == ClarificationAnswerErrorCode.RELEASE_MISMATCH


def test_question_and_rules_artifact_mismatch_fails_closed(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _ambiguous_shape_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    answer = _answer(
        plan,
        question,
        session_id=uuid4(),
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option="oval",
    )
    wrong_questions = SimpleNamespace(artifact_version="9.9.9")
    with pytest.raises(ClarificationAnswerError) as question_error:
        _process(
            plan,
            answer,
            revision,
            active_release,
            runtime_artifacts,
            questions=wrong_questions,
        )
    assert question_error.value.code == ClarificationAnswerErrorCode.ARTIFACT_MISMATCH

    wrong_rules = SimpleNamespace(artifact_version="9.9.9")
    with pytest.raises(ClarificationAnswerError) as rules_error:
        _process(
            plan,
            answer,
            revision,
            active_release,
            runtime_artifacts,
            rules=wrong_rules,
        )
    assert rules_error.value.code == ClarificationAnswerErrorCode.ARTIFACT_MISMATCH


@pytest.mark.parametrize(("confirmed", "locked"), [(True, False), (True, True)])
def test_confirmed_and_locked_targets_cannot_be_overwritten(
    confirmed,
    locked,
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _preference_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    payload = revision.model_dump(mode="json")
    protected = copy.deepcopy(ring.model_dump(mode="json")["design"]["metal"]["color"])
    protected["confirmed"] = confirmed
    protected["locked"] = locked
    payload["design"]["metal"]["color"] = protected
    authoritative = DesignRevision.model_validate(payload)
    answer = _answer(
        plan,
        question,
        session_id=uuid4(),
        decision=ClarificationDecision.ACCEPT,
    )

    result = _process(plan, answer, authoritative, active_release, runtime_artifacts)

    assert result.outcome == ClarificationAnswerOutcome.DEFERRED
    assert result.reason == ClarificationAnswerReason.TARGET_PROTECTED
    assert result.new_revision_id is None
    assert authoritative.design.metal.color.value == "white"


def test_duplicate_is_idempotent_and_conflicting_repeat_is_rejected(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, question = _ambiguous_shape_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    session_id = uuid4()
    emerald = _answer(
        plan,
        question,
        session_id=session_id,
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option="emerald_cut",
    )
    first = _process(plan, emerald, revision, active_release, runtime_artifacts)

    duplicate = _process(
        plan,
        emerald,
        revision,
        active_release,
        runtime_artifacts,
        previous_results=(first,),
    )
    assert duplicate == first
    assert duplicate.content_hash == first.content_hash
    assert duplicate.new_revision_id == first.new_revision_id

    oval = emerald.model_copy(update={"selected_option": "oval"})
    with pytest.raises(ClarificationAnswerError) as conflict:
        _process(
            plan,
            oval,
            revision,
            active_release,
            runtime_artifacts,
            previous_results=(first,),
        )
    assert conflict.value.code == ClarificationAnswerErrorCode.CONFLICTING_ANSWER


def test_unsupported_rule_answer_never_creates_groups_or_mutates_state(
    ring,
    dictionary,
    templates,
    active_release,
    runtime_artifacts,
):
    revision, plan, _ = _preference_plan(
        ring, dictionary, templates, active_release, runtime_artifacts
    )
    required_without_options = next(
        item
        for item in plan.questions
        if item.category == ClarificationCategory.REQUIRED_INFORMATION and not item.options
    )
    answer = _answer(
        plan,
        required_without_options,
        session_id=uuid4(),
        decision=ClarificationDecision.SELECT_OPTION,
        selected_option="invented",
    )
    before = copy.deepcopy(revision)

    with pytest.raises(ClarificationAnswerError) as error:
        _process(plan, answer, revision, active_release, runtime_artifacts)

    assert error.value.code == ClarificationAnswerErrorCode.INVALID_OPTION
    assert revision == before
    assert revision.design.side_stones == before.design.side_stones


def test_constraint_evidence_supersession_reaffirmation_and_ambiguity_are_deterministic(
    ring, dictionary, templates, active_release
):
    _, initial = _enrich(
        "No halo.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    session_id = uuid4()
    organization_id = uuid4()
    first_cycle = uuid4()
    first = merge_constraint_evidence(
        initial,
        session_id=session_id,
        organization_id=organization_id,
        source=initial.parser_proposal.source,
        authoritative_revision=ring,
        enrichment_cycle_id=first_cycle,
    )
    assert len(first) == 1
    assert first[0].kind == "prohibition"
    assert first[0].status == "active"
    assert first[0].semantic_subject == "feature.halo"

    _, correction = _enrich(
        "Actually, add a halo.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    corrected = merge_constraint_evidence(
        correction,
        session_id=session_id,
        organization_id=organization_id,
        source=correction.parser_proposal.source,
        authoritative_revision=ring,
        enrichment_cycle_id=uuid4(),
        previous=first,
    )
    active = [item for item in corrected if item.status == "active"]
    superseded = [item for item in corrected if item.status == "superseded"]
    assert len(active) == len(superseded) == 1
    assert active[0].kind == "requirement"
    assert superseded[0].superseded_by_evidence_id == active[0].evidence_id

    _, ambiguous = _enrich(
        "Don't change that part.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    with_ambiguous = merge_constraint_evidence(
        ambiguous,
        session_id=session_id,
        organization_id=organization_id,
        source=ambiguous.parser_proposal.source,
        authoritative_revision=ring,
        enrichment_cycle_id=uuid4(),
        previous=corrected,
    )
    unresolved = [item for item in with_ambiguous if item.status == "unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0].semantic_subject is None
    assert [item for item in with_ambiguous if item.status == "active"] == active


def test_preservation_evidence_is_active_but_does_not_mutate_product_state(
    ring, dictionary, templates, active_release
):
    before = ring.model_dump_json()
    _, enrichment = _enrich(
        "Change the center stone to round, but keep the original band.",
        locale="en",
        revision=ring,
        dictionary=dictionary,
        templates=templates,
        active_release=active_release,
    )
    evidence = merge_constraint_evidence(
        enrichment,
        session_id=uuid4(),
        organization_id=uuid4(),
        source=enrichment.parser_proposal.source,
        authoritative_revision=ring,
        enrichment_cycle_id=uuid4(),
    )

    preserved = next(item for item in evidence if item.semantic_subject == "component.band")
    assert preserved.kind == "preservation"
    assert preserved.status == "active"
    assert ring.model_dump_json() == before


@pytest.mark.parametrize(
    "mode", ["same-value", "changed-value", "missing-source", "wrong-revision", "wrong-design"]
)
def test_canonical_keep_compatibility_uses_exact_authoritative_source(ring, mode):
    from jewelai_domain.models_v1_1 import DesignRevisionV1_1, upgrade_design_revision_v1_to_v1_1
    from jewelai_domain.revisions import revise_design

    from jewelai_api.constraint_evidence import (
        ConstraintEvidenceIntegrityError,
        _same_preserved_fact,
    )

    source = MessageSource(message_id=str(uuid4()), recorded_at=NOW)
    payload = upgrade_design_revision_v1_to_v1_1(ring).model_dump(mode="json")

    def explicit(value):
        return dict(
            availability="value",
            origin="explicit",
            value=value,
            source=source.model_dump(mode="json"),
            confirmed=False,
            locked=False,
        )

    payload["design"]["composition"] = explicit({"symmetry_mode": explicit("asymmetrical")})
    original = DesignRevisionV1_1.model_validate(payload)
    changed = original.design.model_dump(mode="json")
    child = changed["composition"]["value"]["symmetry_mode"]
    child["value"] = "symmetrical" if mode == "changed-value" else "asymmetrical"
    child["source"]["message_id"] = str(uuid4())
    current = revise_design(
        original,
        changed,
        expected_revision_id=original.revision_id,
        source=source,
        reason="Explicit test canonical edit",
        created_at=NOW,
    )
    keeper = SimpleNamespace(
        source_revision_id=original.revision_id, semantic_subject="composition.symmetry_mode"
    )
    requirement = SimpleNamespace(kind="requirement", canonical_target="composition.symmetry_mode")
    returned = original.model_dump(mode="json")
    if mode == "wrong-revision":
        returned["revision_id"] = str(uuid4())
    if mode == "wrong-design":
        returned["design_id"] = str(uuid4())
    calls = []

    def load(revision_id):
        calls.append(revision_id)
        return DesignRevisionV1_1.model_validate(returned)

    if mode in {"missing-source", "wrong-revision", "wrong-design"}:
        with pytest.raises(ConstraintEvidenceIntegrityError):
            _same_preserved_fact(
                keeper, requirement, current, None if mode == "missing-source" else load
            )
    else:
        assert _same_preserved_fact(keeper, requirement, current, load) is (mode == "same-value")
        assert calls == [original.revision_id]
    # The compatibility rule neither mutates canonical values nor introduces LOCK.
    assert not current.design.composition.value.symmetry_mode.locked
    assert original.design.composition.value.symmetry_mode.value == "asymmetrical"
