"""Actual pinned core candidate checks; no synthetic ACTIVE/PASS envelope.

Test proposals are adversarial test inputs, never candidate content. These
checks do not establish original P0 corpus recovery or full release readiness.
"""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jewelai_domain.knowledge_activation import KnowledgeActivationError
from jewelai_domain.knowledge_activation_v1_1 import (
    ProductionValidationReportV1_1,
    validate_for_production_v1_1,
)
from jewelai_domain.knowledge_library_v1_1 import (
    compile_knowledge_library_v1_1,
    validate_knowledge_library_v1_1,
)
from jewelai_domain.knowledge_policy import (
    KnowledgePolicyEngine,
    RuntimeProvenance,
    RuntimeSemanticState,
)
from jewelai_domain.knowledge_qualification_v1_1 import qualify_knowledge_release_v1_1
from jewelai_domain.knowledge_storage import KnowledgeArtifactStorageError
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from jewelai_domain.knowledge_targets_v1_1 import PRODUCT_STATE_TARGET_FAMILIES_V1_1
from jewelai_domain.models import DesignRevision
from jewelai_parser import KnowledgeLibraryMatcher, ResolvedKnowledgeMatch

from jewelai_prompts import EnrichmentProposal, enrich_prompt, load_prompt_templates

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "recovered_draft", ROOT / "tools/knowledge/build_recovered_draft.py"
)
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


@pytest.fixture
def candidate():
    return packaging.project_core(packaging.SOURCE.read_bytes())


@pytest.fixture
def runtime(candidate):
    return compile_knowledge_library_v1_1(candidate)[0]


def test_actual_core_projection_is_lossless_and_explicit(candidate, runtime):
    original = json.loads(packaging.SOURCE.read_bytes())
    raw = candidate.model_dump(mode="json")
    assert candidate.contract_version == runtime.schema_version == "1.1.0"
    assert candidate.package_id == "jewelai.draft.recovered_core"
    assert [len(getattr(candidate, group)) for group in packaging.RECORD_GROUPS] == [
        11,
        13,
        117,
        211,
        30,
    ]
    for group in packaging.RECORD_GROUPS:
        for old, new in zip(original[group], raw[group], strict=True):
            assert {key: new[key] for key in old} == old
            assert new["lifecycle_status"] == "REVIEWED"
    assert runtime.active_for_production is False
    assert compile_knowledge_library_v1_1(candidate)[0] == runtime


def test_projection_rejects_changed_or_retagged_source():
    for data in (
        packaging.SOURCE.read_bytes() + b" ",
        packaging.SOURCE.read_bytes().replace(b'"1.0.0"', b'"1.1.0"', 1),
    ):
        with pytest.raises(ValueError, match="unauthenticated"):
            packaging.project_core(data)


def test_actual_candidate_store_is_immutable_and_tamper_fails_closed(candidate, tmp_path):
    store = KnowledgeArtifactStoreV1_1(tmp_path)
    first = store.publish(candidate)
    assert store.publish(candidate) == store.load(candidate.package_id, "0.1.0") == first
    altered = candidate.model_dump(mode="json")
    altered["claims"][0]["statement"] += " adversarial modification"
    with pytest.raises(KnowledgeArtifactStorageError, match="different content"):
        store.publish(altered)
    path = Path(first.release_path) / "runtime.json"
    path.write_text(path.read_text().replace('"COMPILED"', '"DRAFT"', 1))
    with pytest.raises(KnowledgeArtifactStorageError):
        store.load(candidate.package_id, "0.1.0")


@pytest.mark.parametrize("defect", ["source", "concept", "target", "lifecycle"])
def test_actual_candidate_invalid_references_fail(candidate, defect):
    altered = candidate.model_dump(mode="json")
    if defect == "source":
        altered["claims"][0]["source_id"] = "MISSING-SOURCE"
    elif defect == "concept":
        altered["language_mappings"][0]["concept_id"] = "missing.concept"
    elif defect == "target":
        altered["policies"][0]["target"] = "arbitrary.unknown"
    else:
        altered["policies"][0]["lifecycle_status"] = "ACTIVE"
    with pytest.raises(ValueError):
        validate_knowledge_library_v1_1(altered)


def test_all_actual_language_records_preserve_their_resolution(runtime):
    matcher = KnowledgeLibraryMatcher(runtime)
    surfaces = 0
    for mapping in runtime.language_mappings:
        for surface in (mapping.canonical_term, *mapping.aliases):
            result = matcher.match(surface, locale=mapping.locale, context=mapping.context)
            if isinstance(result, ResolvedKnowledgeMatch):
                assert result.candidate.concept_id == mapping.concept_id
            else:
                assert mapping.concept_id in {item.concept_id for item in result.candidates}
            surfaces += 1
    assert surfaces >= 211


def test_actual_policy_targets_and_canonical_protection(runtime):
    ring = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_bytes()
    )
    before = ring.model_dump(mode="json")
    templates = load_prompt_templates(ROOT / "data/prompts/v1.0.0.json")
    engine = KnowledgePolicyEngine(runtime)
    for policy in runtime.policies:
        concrete = policy.target.replace("{group_id}", "accents")
        assert policy in engine.policies_for(concrete, existing_group_ids=("accents",))
    result = enrich_prompt(
        ring,
        templates,
        runtime,
        proposals=(
            EnrichmentProposal(
                target="metal.color",
                value="yellow",
                semantic_state=RuntimeSemanticState.NORMALIZED,
                provenance=RuntimeProvenance.USER_CONFIRMED,
                source_id="DEC-JEWELAI-PRODUCTION-CATALOG-V1",
            ),
            EnrichmentProposal(
                target="side_stones.not_present.stones.shape",
                value="round",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                source_id="DEC-JEWELAI-PRODUCTION-CATALOG-V1",
            ),
        ),
    )
    decisions = {item.target: item for item in result.decisions}
    assert decisions["metal.color"].reason == "locked"
    assert decisions["metal.color"].result.value == "white"
    assert decisions["side_stones.not_present.stones.shape"].reason == "unknown_target"
    assert decisions["metal.color"].applicable_policy_ids == ("POL-PROD-03-METAL-COLOR",)
    assert ring.model_dump(mode="json") == before
    assert result.knowledge_runtime_sha256 == runtime.sha256
    assert len(PRODUCT_STATE_TARGET_FAMILIES_V1_1) == 148
    assert result.enrichment_version == "1.3.0"


def test_actual_candidate_en_ru_and_no_false_equivalences(runtime):
    matcher = KnowledgeLibraryMatcher(runtime)
    for text, locale, expected in (
        ("oval", "en", "oval"),
        ("овал", "ru", "oval"),
        ("platinum", "en", "platinum"),
        ("платина", "ru", "platinum"),
    ):
        result = matcher.match(text, locale=locale)
        assert isinstance(result, ResolvedKnowledgeMatch)
        assert result.candidate.concept_id == expected
    assert matcher.match("round", locale="en").candidate.concept_id == "round"
    assert matcher.match("rose", locale="en").candidate.concept_id != (
        matcher.match("red", locale="en").candidate.concept_id
    )


def test_actual_candidate_does_not_bypass_active_or_qualification(candidate, runtime, tmp_path):
    store = KnowledgeArtifactStoreV1_1(tmp_path)
    store.publish(candidate)
    report = ProductionValidationReportV1_1(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=(
            {
                "name": "compiler_contract",
                "outcome": "PASS",
                "evidence_ref": "test_actual_core_projection_is_lossless_and_explicit",
            },
            {
                "name": "provenance_integrity",
                "outcome": "EXPECTED_GAP",
                "evidence_ref": "Original P0 item-level source linkage remains unverified",
            },
        ),
    )
    with pytest.raises(KnowledgeActivationError):
        validate_for_production_v1_1(runtime, report)
    qualification = qualify_knowledge_release_v1_1(
        store,
        {"package_id": candidate.package_id, "artifact_version": "0.1.0"},
        validation_report=report,
    )
    assert qualification.status == "BLOCKED"
    assert qualification.blockers[0].code == "active_envelope_missing"


def test_recovery_reconciliation_rejects_forged_record(candidate, monkeypatch):
    # Synthetic recovery mutation tests only; actual 1,240 rows are private evidence.
    source = packaging.SOURCE.read_bytes()
    original = json.loads(source)
    recovered = []
    for group, id_field in packaging.RECORD_GROUPS.items():
        for index, record in enumerate(original[group]):
            recovered.append(
                {
                    "nav": f"{group}-{index}",
                    "id": record[id_field],
                    "type": group,
                    "file": "data/knowledge/v1/jewelry-core-1.0.0.json",
                    "pointer": f"/{group}/{index}",
                    "object": record,
                    "sourceSha": packaging.SOURCE_SHA256,
                    "recovery": "VERBATIM_RECOVERED",
                    "lifecycle": record["lifecycle_status"],
                    "url": "test-only-recovery",
                }
            )
    encoded = packaging.canonical(recovered)
    monkeypatch.setattr(packaging, "RECOVERY_SHA256", packaging.sha256(encoded))
    included, excluded = packaging.reconcile_recovery(candidate, source, encoded)
    assert len(included) == 382 and excluded == []
    for mutate in ("statement", "lifecycle", "missing", "duplicate"):
        changed = deepcopy(recovered)
        if mutate == "statement":
            changed[11]["object"]["statement"] += " forged"
        elif mutate == "lifecycle":
            changed[0]["lifecycle"] = "ACTIVE"
        elif mutate == "missing":
            changed.pop()
        else:
            changed.append(changed[0])
        payload = packaging.canonical(changed)
        monkeypatch.setattr(packaging, "RECOVERY_SHA256", packaging.sha256(payload))
        with pytest.raises(ValueError):
            packaging.reconcile_recovery(candidate, source, payload)
