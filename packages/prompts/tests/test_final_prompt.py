import hashlib
import inspect
import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from jewelai_domain.dictionary import load_domain_dictionary
from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary, CompiledPolicy
from jewelai_domain.knowledge_policy import RuntimeProvenance, RuntimeSemanticState
from jewelai_domain.models import DesignRevision
from jewelai_domain.rules import BlockDecision, ReadyDecision, ReasonCode
from pydantic import ValidationError

from jewelai_prompts import (
    CompiledPrompt,
    EnrichmentProposal,
    FinalPromptArtifactVersions,
    FinalPromptDecisionLineage,
    FinalPromptInputError,
    FinalPromptInputErrorCode,
    FinalPromptReadiness,
    FinalPromptSnapshot,
    KnowledgeReleaseReference,
    PromptEnrichmentResult,
    assemble_internal_final_prompt,
    enrich_prompt,
    load_prompt_templates,
)
from jewelai_prompts.final_schema import internal_final_prompt_json_schema

ROOT = Path(__file__).resolve().parents[3]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
DICTIONARY = ROOT / "data" / "dictionary" / "v1.0.0.json"
TEMPLATES = ROOT / "data" / "prompts" / "v1.0.0.json"
SESSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ORGANIZATION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
CYCLE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
REPORT_HASH = "a" * 64


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(DICTIONARY)


@pytest.fixture(scope="module")
def templates():
    return load_prompt_templates(TEMPLATES)


@pytest.fixture
def ring():
    return DesignRevision.model_validate_json(RING.read_text())


@pytest.fixture(scope="module")
def runtime():
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.final-prompt",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(
            CompiledPolicy(
                policy_id="POL-SETTING",
                target="center_stone.setting",
                effect="Offer a setting without making it a user requirement.",
                source_kind="INTERNAL_PRODUCT_DECISION",
                source_refs=("DEC-1",),
            ),
        ),
    )


def _hash(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _verified_enrichment(revision, templates, runtime, *, proposals=()):
    result = enrich_prompt(revision, templates, runtime, proposals=proposals)
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    payload["knowledge_validation_report_sha256"] = REPORT_HASH
    return PromptEnrichmentResult(**payload, content_hash=_hash(payload))


def _ready():
    return ReadyDecision(
        rule_id="ready_for_visualization",
        rule_version="1.0.0",
        rules_artifact_version="1.0.0",
        reason_code=ReasonCode.ALL_REQUIRED_FIELDS_SATISFIED,
        reason="All authoritative required targets are satisfied.",
        priority=1,
        tie_order=1,
        trace=(),
    )


def _blocked():
    return BlockDecision(
        rule_id="blocked_missing_required",
        rule_version="1.0.0",
        rules_artifact_version="1.0.0",
        reason_code=ReasonCode.NO_VALID_DECISION,
        reason="An authoritative blocking decision remains.",
        priority=2,
        tie_order=2,
        target=None,
        concrete_target=None,
        trace=(),
    )


def _snapshot(revision, enrichment, *, locale="en", lineage=(), **changes):
    payload = {
        "session_id": SESSION_ID,
        "organization_id": ORGANIZATION_ID,
        "locale": locale,
        "revision": revision,
        "enrichment_cycle_id": CYCLE_ID,
        "latest_enrichment_cycle_id": CYCLE_ID,
        "enrichment_cycle_number": 2,
        "enrichment_result": enrichment,
        "knowledge_release": KnowledgeReleaseReference(
            package_id=enrichment.knowledge_package_id,
            artifact_version=enrichment.knowledge_artifact_version,
            runtime_sha256=enrichment.knowledge_runtime_sha256,
            validation_report_sha256=REPORT_HASH,
        ),
        "artifact_versions": FinalPromptArtifactVersions(
            design_schema_version=revision.schema_version,
            dictionary_artifact_version="1.0.0",
            question_artifact_version="1.0.0",
            rules_artifact_version="1.0.0",
            prompt_template_artifact_version="1.0.0",
            enrichment_version=enrichment.enrichment_version,
        ),
        "rule_decision": _ready(),
        "decision_lineage": lineage,
    }
    payload.update(changes)
    return FinalPromptSnapshot(**payload)


def _assemble(revision, templates, runtime, dictionary, **snapshot_changes):
    enrichment = _verified_enrichment(revision, templates, runtime)
    return assemble_internal_final_prompt(
        _snapshot(revision, enrichment, **snapshot_changes),
        dictionary=dictionary,
        templates=templates,
    )


def _changed(revision, mutator, *, revision_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd"):
    payload = revision.model_dump(mode="json")
    payload["revision"] += 1
    payload["parent_revision_id"] = payload["revision_id"]
    payload["revision_id"] = revision_id
    payload["event"]["action"] = "edit"
    mutator(payload["design"])
    return DesignRevision.model_validate(payload)


def test_builds_deterministic_provider_neutral_outputs(ring, templates, runtime, dictionary):
    snapshot = _snapshot(ring, _verified_enrichment(ring, templates, runtime))
    first = assemble_internal_final_prompt(snapshot, dictionary=dictionary, templates=templates)
    second = assemble_internal_final_prompt(snapshot, dictionary=dictionary, templates=templates)

    assert first == second
    prompt = first.internal_final_prompt
    assert prompt.schema_version == "1.0.0"
    assert prompt.product_state_revision_id == ring.revision_id
    assert prompt.knowledge_release.runtime_sha256 == runtime.sha256
    assert prompt.description_content_hash == first.description.content_hash
    assert prompt.content_hash == _hash(prompt.model_dump(mode="json", exclude={"content_hash"}))
    assert "google" not in prompt.prompt_text.casefold()
    assert "openai" not in prompt.prompt_text.casefold()
    assert "model" not in prompt.model_dump_json().casefold()


def test_english_and_russian_descriptions_share_meaning_without_internal_ids(
    ring, templates, runtime, dictionary
):
    enrichment = _verified_enrichment(ring, templates, runtime)
    english = assemble_internal_final_prompt(
        _snapshot(ring, enrichment), dictionary=dictionary, templates=templates
    )
    russian = assemble_internal_final_prompt(
        _snapshot(ring, enrichment, locale="ru"), dictionary=dictionary, templates=templates
    )

    assert "Current design: ring" in english.description.text
    assert "Center stone: material emerald, shape oval" in english.description.text
    assert "Текущий дизайн: кольцо" in russian.description.text
    assert "Центральный камень: материал изумруд, форма овал" in russian.description.text
    assert english.internal_final_prompt.design_facts == russian.internal_final_prompt.design_facts
    for forbidden in (str(SESSION_ID), str(CYCLE_ID), str(ring.revision_id), "accents"):
        assert forbidden not in english.description.text
        assert forbidden not in russian.description.text


def test_locked_confirmed_values_and_prohibitions_are_preserved(
    ring, templates, runtime, dictionary
):
    source = ring.event.source.model_dump(mode="json")
    revision = _changed(
        ring,
        lambda design: design["style"].update(
            {
                "availability": "not_applicable",
                "origin": "explicit",
                "value": None,
                "reason": "No halo or other surrounding style.",
                "source": source,
                "confirmed": True,
                "locked": True,
            }
        ),
    )
    result = _assemble(revision, templates, runtime, dictionary)
    constraints = {(item.kind, item.target) for item in result.internal_final_prompt.constraints}

    assert ("preservation", "metal.color") in constraints
    assert ("prohibition", "style") in constraints
    assert ("preservation", "style") in constraints
    assert "Explicitly excluded: style" in result.description.text
    assert "No halo or other surrounding style" in result.description.text
    assert "No halo or other surrounding style" in result.internal_final_prompt.prompt_text


def test_unaccepted_recommendation_is_evidence_not_requirement(
    ring, templates, runtime, dictionary
):
    proposal = EnrichmentProposal(
        target="center_stone.setting",
        semantic_state=RuntimeSemanticState.RECOMMENDED,
        provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
        value="prong_setting",
        source_id="REC-SETTING",
    )
    enrichment = _verified_enrichment(ring, templates, runtime, proposals=(proposal,))
    result = assemble_internal_final_prompt(
        _snapshot(ring, enrichment), dictionary=dictionary, templates=templates
    )

    assert "center_stone.setting" not in {
        item.target for item in result.internal_final_prompt.design_facts
    }
    assert not result.internal_final_prompt.enrichment_evidence[0].accepted_as_requirement
    assert any(
        item.target == "center_stone.setting" and item.classification == "unaccepted_recommendation"
        for item in result.internal_final_prompt.unresolved_details
    )


def test_rejected_recommendation_remains_non_authoritative(ring, templates, runtime, dictionary):
    proposal = EnrichmentProposal(
        target="center_stone.setting",
        semantic_state=RuntimeSemanticState.RECOMMENDED,
        provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
        value="prong_setting",
        source_id="REC-REJECTED",
    )
    enrichment = _verified_enrichment(ring, templates, runtime, proposals=(proposal,))
    lineage = (
        FinalPromptDecisionLineage(
            kind="clarification",
            session_id=SESSION_ID,
            decision_id="reject-setting",
            decision="REJECT",
            outcome="REJECTED",
            target="center_stone.setting",
            selected_value="prong_setting",
            source_revision_id=ring.revision_id,
            applies_to_revision_id=ring.revision_id,
            knowledge_package_id="jewelai.test.final-prompt",
            knowledge_artifact_version="1.0.0",
            knowledge_runtime_sha256=runtime.sha256,
            knowledge_validation_report_sha256=REPORT_HASH,
            question_artifact_version="1.0.0",
            rules_artifact_version="1.0.0",
            content_hash="2" * 64,
        ),
    )
    result = assemble_internal_final_prompt(
        _snapshot(ring, enrichment, lineage=lineage),
        dictionary=dictionary,
        templates=templates,
    ).internal_final_prompt
    assert "center_stone.setting" not in {item.target for item in result.design_facts}
    assert not result.enrichment_evidence[0].accepted_as_requirement
    assert result.decision_lineage[0].outcome == "REJECTED"


def test_explicitly_accepted_recommendation_is_authoritative(ring, templates, runtime, dictionary):
    source = {
        "kind": "knowledge",
        "record_id": "REC-SETTING",
        "version": "1.0.0",
        "recorded_at": "2026-09-20T12:00:00Z",
    }
    revision = _changed(
        ring,
        lambda design: design["center_stone"].update(
            {
                "setting": {
                    "availability": "value",
                    "origin": "derived",
                    "value": "prong_setting",
                    "sources": [source],
                    "uncertainty": "Accepted reviewed recommendation.",
                    "confirmed": True,
                    "locked": False,
                }
            }
        ),
    )
    result = _assemble(revision, templates, runtime, dictionary)
    fact = next(
        item
        for item in result.internal_final_prompt.design_facts
        if item.target == "center_stone.setting"
    )
    assert fact.semantic_state == RuntimeSemanticState.ACCEPTED
    assert fact.provenance == RuntimeProvenance.USER_ACCEPTED_RECOMMENDATION
    assert "setting prong setting" in result.description.text


def test_accepted_preference_lineage_is_retained_without_becoming_separate_authority(
    ring, templates, runtime, dictionary
):
    lineage = (
        FinalPromptDecisionLineage(
            kind="clarification",
            session_id=SESSION_ID,
            decision_id="accepted-white-metal",
            decision="ACCEPT",
            outcome="APPLIED",
            target="metal.color",
            selected_value="white",
            source_revision_id=ring.revision_id,
            applies_to_revision_id=ring.revision_id,
            knowledge_package_id="jewelai.test.final-prompt",
            knowledge_artifact_version="1.0.0",
            knowledge_runtime_sha256=runtime.sha256,
            knowledge_validation_report_sha256=REPORT_HASH,
            question_artifact_version="1.0.0",
            rules_artifact_version="1.0.0",
            content_hash="1" * 64,
        ),
    )
    result = _assemble(ring, templates, runtime, dictionary, lineage=lineage).internal_final_prompt
    metal = next(item for item in result.design_facts if item.target == "metal.color")
    assert metal.value == "white"
    assert result.decision_lineage == lineage


@pytest.mark.parametrize(
    ("outcome", "classification"),
    [("SKIPPED", "skipped"), ("UNKNOWN", "unknown"), ("DEFERRED", "deferred")],
)
def test_optional_decisions_remain_unresolved_without_invented_values(
    ring, templates, runtime, dictionary, outcome, classification
):
    lineage = (
        FinalPromptDecisionLineage(
            kind="clarification" if outcome != "DEFERRED" else "correction",
            session_id=SESSION_ID,
            decision_id=f"decision-{outcome.casefold()}",
            decision=outcome,
            outcome=outcome,
            target="construction.shank_width",
            source_revision_id=ring.revision_id,
            applies_to_revision_id=ring.revision_id,
            knowledge_package_id="jewelai.test.final-prompt",
            knowledge_artifact_version="1.0.0",
            knowledge_runtime_sha256=runtime.sha256,
            knowledge_validation_report_sha256=REPORT_HASH,
            question_artifact_version="1.0.0" if outcome != "DEFERRED" else None,
            rules_artifact_version="1.0.0" if outcome != "DEFERRED" else None,
            blocks_progression=False,
            content_hash="b" * 64,
        ),
    )
    result = _assemble(ring, templates, runtime, dictionary, lineage=lineage).internal_final_prompt
    assert result.readiness == FinalPromptReadiness.READY_WITH_UNRESOLVED
    assert any(item.classification == classification for item in result.unresolved_details)
    assert "construction.shank_width" not in {item.target for item in result.design_facts}
    assert "mm" not in result.prompt_text.split("construction.shank_width", 1)[-1][:30]


def test_correction_uses_latest_revision_without_resurrecting_old_value(
    ring, templates, runtime, dictionary
):
    revision = _changed(
        ring,
        lambda design: design["center_stone"]["shape"].update({"value": "emerald_cut"}),
    )
    lineage = (
        FinalPromptDecisionLineage(
            kind="correction",
            session_id=SESSION_ID,
            decision_id="correction-round-shape",
            decision="CORRECT",
            outcome="APPLIED",
            target="center_stone.shape",
            selected_value="emerald_cut",
            source_revision_id=ring.revision_id,
            resulting_revision_id=revision.revision_id,
            applies_to_revision_id=revision.revision_id,
            knowledge_package_id="jewelai.test.final-prompt",
            knowledge_artifact_version="1.0.0",
            knowledge_runtime_sha256=runtime.sha256,
            knowledge_validation_report_sha256=REPORT_HASH,
            content_hash="c" * 64,
        ),
    )
    result = _assemble(
        revision, templates, runtime, dictionary, lineage=lineage
    ).internal_final_prompt
    shape = next(item for item in result.design_facts if item.target == "center_stone.shape")
    assert shape.value == "emerald_cut"
    assert "oval" not in result.prompt_text
    assert result.decision_lineage == lineage


def test_multiple_side_stone_groups_remain_distinct_and_do_not_expose_group_ids(
    ring, templates, runtime, dictionary
):
    def add_group(design):
        second = deepcopy(design["side_stones"][0])
        second["group_id"] = "second_group"
        second["stones"]["shape"]["value"] = "emerald_cut"
        design["side_stones"] = [second, design["side_stones"][0]]

    revision = _changed(ring, add_group)
    result = _assemble(revision, templates, runtime, dictionary)
    side_targets = [
        item.target
        for item in result.internal_final_prompt.design_facts
        if item.target.startswith("side_stones.")
    ]
    group_order = tuple(dict.fromkeys(item.split(".")[1] for item in side_targets))
    assert group_order == ("accents", "second_group")
    assert "Side-stone group 1" in result.description.text
    assert "Side-stone group 2" in result.description.text
    assert "accents" not in result.description.text
    assert "second_group" not in result.description.text


def test_inputs_and_existing_compiled_prompt_are_not_mutated(ring, templates, runtime, dictionary):
    enrichment = _verified_enrichment(ring, templates, runtime)
    before_revision = ring.model_dump_json()
    before_prompt = enrichment.compiled_prompt
    assemble_internal_final_prompt(
        _snapshot(ring, enrichment), dictionary=dictionary, templates=templates
    )
    assert ring.model_dump_json() == before_revision
    assert enrichment.compiled_prompt == before_prompt
    assert isinstance(enrichment.compiled_prompt, CompiledPrompt)


def test_fails_closed_for_stale_revision(ring, templates, runtime, dictionary):
    enrichment = _verified_enrichment(ring, templates, runtime)
    stale = _changed(ring, lambda design: None)
    with pytest.raises(FinalPromptInputError) as caught:
        assemble_internal_final_prompt(
            _snapshot(stale, enrichment), dictionary=dictionary, templates=templates
        )
    assert caught.value.code == FinalPromptInputErrorCode.STALE_REVISION


def test_existing_authoritative_blocking_decision_is_preserved(
    ring, templates, runtime, dictionary
):
    result = _assemble(
        ring,
        templates,
        runtime,
        dictionary,
        rule_decision=_blocked(),
    ).internal_final_prompt
    assert result.readiness == FinalPromptReadiness.BLOCKED
    assert result.readiness_reason == "An authoritative blocking decision remains."


def test_rejects_nonlatest_enrichment_cycle(ring, templates, runtime, dictionary):
    enrichment = _verified_enrichment(ring, templates, runtime)
    with pytest.raises(FinalPromptInputError) as caught:
        assemble_internal_final_prompt(
            _snapshot(
                ring,
                enrichment,
                latest_enrichment_cycle_id=UUID("99999999-9999-4999-8999-999999999999"),
            ),
            dictionary=dictionary,
            templates=templates,
        )
    assert caught.value.code == FinalPromptInputErrorCode.ENRICHMENT_CYCLE_MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        {
            "knowledge_release": KnowledgeReleaseReference(
                package_id="wrong.package",
                artifact_version="1.0.0",
                runtime_sha256="d" * 64,
                validation_report_sha256=REPORT_HASH,
            )
        },
        {
            "artifact_versions": FinalPromptArtifactVersions(
                design_schema_version="1.0.0",
                dictionary_artifact_version="9.9.9",
                question_artifact_version="1.0.0",
                rules_artifact_version="1.0.0",
                prompt_template_artifact_version="1.0.0",
                enrichment_version="1.1.0",
            )
        },
    ],
)
def test_fails_closed_for_release_or_artifact_mismatch(
    ring, templates, runtime, dictionary, change
):
    enrichment = _verified_enrichment(ring, templates, runtime)
    with pytest.raises(FinalPromptInputError) as caught:
        assemble_internal_final_prompt(
            _snapshot(ring, enrichment, **change), dictionary=dictionary, templates=templates
        )
    assert caught.value.code in {
        FinalPromptInputErrorCode.KNOWLEDGE_RELEASE_MISMATCH,
        FinalPromptInputErrorCode.ARTIFACT_MISMATCH,
    }


def test_rejects_invalid_hash_and_cross_session_lineage(ring, templates, runtime, dictionary):
    enrichment = _verified_enrichment(ring, templates, runtime)
    invalid = _snapshot(ring, enrichment).model_dump(mode="json")
    invalid["enrichment_result"]["content_hash"] = "0" * 64
    with pytest.raises(FinalPromptInputError) as caught:
        assemble_internal_final_prompt(invalid, dictionary=dictionary, templates=templates)
    assert caught.value.code == FinalPromptInputErrorCode.INVALID_SNAPSHOT

    lineage = (
        FinalPromptDecisionLineage(
            kind="clarification",
            session_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
            decision_id="foreign-answer",
            decision="UNKNOWN",
            outcome="UNKNOWN",
            target="center_stone.dimensions",
            source_revision_id=ring.revision_id,
            applies_to_revision_id=ring.revision_id,
            knowledge_package_id="jewelai.test.final-prompt",
            knowledge_artifact_version="1.0.0",
            knowledge_runtime_sha256=runtime.sha256,
            knowledge_validation_report_sha256=REPORT_HASH,
            question_artifact_version="1.0.0",
            rules_artifact_version="1.0.0",
            content_hash="e" * 64,
        ),
    )
    with pytest.raises(FinalPromptInputError) as caught:
        _assemble(ring, templates, runtime, dictionary, lineage=lineage)
    assert caught.value.code == FinalPromptInputErrorCode.CROSS_SESSION_LINEAGE


def test_contract_schema_is_versioned_and_no_network_or_provider_dependency():
    schema = internal_final_prompt_json_schema()
    assert schema["$id"] == "urn:jewelai:prompt-enrichment-final-output:1.0.0"
    assert (
        json.loads((ROOT / "specs" / "prompts" / "internal-final-prompt-schema.json").read_text())
        == schema
    )
    source = inspect.getsource(assemble_internal_final_prompt)
    assert "requests" not in source
    assert "http" not in source
    assert "google" not in source.casefold()
    assert "openai" not in source.casefold()


def test_decision_lineage_requires_stable_order(ring, templates, runtime):
    enrichment = _verified_enrichment(ring, templates, runtime)
    first = FinalPromptDecisionLineage(
        kind="correction",
        session_id=SESSION_ID,
        decision_id="z",
        decision="CORRECT",
        outcome="DEFERRED",
        source_revision_id=ring.revision_id,
        applies_to_revision_id=ring.revision_id,
        knowledge_package_id="jewelai.test.final-prompt",
        knowledge_artifact_version="1.0.0",
        knowledge_runtime_sha256=runtime.sha256,
        knowledge_validation_report_sha256=REPORT_HASH,
        content_hash="f" * 64,
    )
    second = first.model_copy(update={"kind": "clarification", "decision_id": "a"})
    with pytest.raises(ValidationError, match="stable"):
        _snapshot(ring, enrichment, lineage=(first, second))
