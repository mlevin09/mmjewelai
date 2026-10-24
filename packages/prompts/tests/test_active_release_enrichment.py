import copy
import json
from pathlib import Path

import pytest
from jewelai_domain import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ProductionValidationCheck,
    ProductionValidationReport,
    RuntimeProvenance,
    RuntimeSemanticState,
    compile_knowledge_library,
    promote_knowledge_runtime,
)
from jewelai_domain.knowledge_storage import (
    KnowledgeArtifactStorageError,
    KnowledgeArtifactStore,
)
from jewelai_domain.models import DesignRevision

from jewelai_prompts import (
    EnrichmentProposal,
    enrich_prompt,
    enrich_prompt_with_active_release,
    load_prompt_templates,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
PROMPTS = ROOT / "data" / "prompts" / "v1.0.0.json"


@pytest.fixture
def ring():
    return DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))


@pytest.fixture
def templates():
    return load_prompt_templates(PROMPTS)


def _bundle(*, version="1.0.0", title_suffix=""):
    payload = json.loads(PACKAGE.read_text(encoding="utf-8"))
    payload["artifact_version"] = version
    if title_suffix:
        payload["sources"][0]["title"] += title_suffix
    return payload


def _report(runtime, *, evidence_suffix=""):
    return ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome="PASS",
                evidence_ref=f"ci://{name}{evidence_suffix}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )


def _publish_active(store, payload):
    stored = store.publish(payload)
    runtime, _ = compile_knowledge_library(payload)
    report = _report(runtime)
    active = promote_knowledge_runtime(runtime, report)
    return stored, runtime, report, active


def _enrich(store, ring, templates, stored, report, active):
    return enrich_prompt_with_active_release(
        ring,
        templates,
        store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        proposals=(
            EnrichmentProposal(
                target="center_stone.shape",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.JEWELAI_RECOMMENDED,
                value="round",
                source_id="POL-THREE-STONE-SIDE-SHAPE",
            ),
        ),
    )


def test_verified_active_release_is_pinned_to_deterministic_enrichment_cycle(
    tmp_path, ring, templates
):
    store = KnowledgeArtifactStore(tmp_path)
    stored, runtime, report, active = _publish_active(store, _bundle())
    revision_before = copy.deepcopy(ring)

    first = _enrich(store, ring, templates, stored, report, active)
    second = _enrich(store, ring, templates, stored, report, active)

    assert first == second
    assert first.knowledge_package_id == active.package_id
    assert first.knowledge_artifact_version == str(active.artifact_version)
    assert first.knowledge_runtime_sha256 == active.runtime_sha256 == runtime.sha256
    assert first.knowledge_validation_report_sha256 == active.validation_report_sha256
    assert first.knowledge_validation_report_sha256 == report.sha256
    assert first.decisions[0].outcome == "KEPT"
    assert first.decisions[0].reason == "lower_precedence"
    assert first.decisions[0].result.value == "oval"
    assert ring == revision_before


def test_legacy_enrichment_serialization_and_hash_remain_unchanged(ring, templates):
    runtime, _ = compile_knowledge_library(_bundle())
    result = enrich_prompt(ring, templates, runtime)
    serialized = result.model_dump(mode="json")

    assert result.knowledge_validation_report_sha256 is None
    assert "knowledge_validation_report_sha256" not in serialized


def test_verified_enrichment_rejects_missing_active_evidence(tmp_path, ring, templates):
    store = KnowledgeArtifactStore(tmp_path)
    stored, runtime, report, _ = _publish_active(store, _bundle())

    for invalid_active in (None, runtime):
        with pytest.raises(KnowledgeArtifactStorageError, match="envelope is missing or invalid"):
            enrich_prompt_with_active_release(
                ring,
                templates,
                store,
                knowledge_package_id=stored.package_id,
                knowledge_artifact_version=stored.artifact_version,
                active_release=invalid_active,
                validation_report=report,
            )


def test_verified_enrichment_rejects_missing_validation_report(tmp_path, ring, templates):
    store = KnowledgeArtifactStore(tmp_path)
    stored, _, _, active = _publish_active(store, _bundle())

    with pytest.raises(KnowledgeArtifactStorageError, match="report is missing or invalid"):
        enrich_prompt_with_active_release(
            ring,
            templates,
            store,
            knowledge_package_id=stored.package_id,
            knowledge_artifact_version=stored.artifact_version,
            active_release=active,
            validation_report=None,
        )


@pytest.mark.parametrize(
    "package_id,artifact_version",
    [
        ("jewelai.validation.other", "1.0.0"),
        ("jewelai.validation.three_stone", "2.0.0"),
    ],
)
def test_verified_enrichment_rejects_selected_identity_mismatch(
    tmp_path, ring, templates, package_id, artifact_version
):
    store = KnowledgeArtifactStore(tmp_path)
    _, _, report, active = _publish_active(store, _bundle())

    with pytest.raises(KnowledgeArtifactStorageError, match="explicitly selected release"):
        enrich_prompt_with_active_release(
            ring,
            templates,
            store,
            knowledge_package_id=package_id,
            knowledge_artifact_version=artifact_version,
            active_release=active,
            validation_report=report,
        )


def test_verified_enrichment_rejects_runtime_substitution(tmp_path, ring, templates):
    store = KnowledgeArtifactStore(tmp_path)
    stored, _, _, _ = _publish_active(store, _bundle())
    substituted_runtime, _ = compile_knowledge_library(_bundle(title_suffix=" changed"))
    substituted_report = _report(substituted_runtime)
    substituted_active = promote_knowledge_runtime(substituted_runtime, substituted_report)

    with pytest.raises(KnowledgeArtifactStorageError, match="runtime SHA-256"):
        _enrich(store, ring, templates, stored, substituted_report, substituted_active)


def test_verified_enrichment_rejects_validation_report_substitution(tmp_path, ring, templates):
    store = KnowledgeArtifactStore(tmp_path)
    stored, runtime, _, active = _publish_active(store, _bundle())
    substituted_report = _report(runtime, evidence_suffix="-substituted")

    with pytest.raises(KnowledgeArtifactStorageError, match="report SHA-256"):
        _enrich(store, ring, templates, stored, substituted_report, active)


def test_validation_report_pin_is_part_of_enrichment_content_hash(tmp_path, ring, templates):
    store = KnowledgeArtifactStore(tmp_path)
    stored, runtime, first_report, first_active = _publish_active(store, _bundle())
    second_report = _report(runtime, evidence_suffix="-revalidated")
    second_active = promote_knowledge_runtime(runtime, second_report)

    first = _enrich(store, ring, templates, stored, first_report, first_active)
    second = _enrich(store, ring, templates, stored, second_report, second_active)

    assert first.initial_matrix == second.initial_matrix
    assert first.decisions == second.decisions
    assert first.final_matrix == second.final_matrix
    assert first.knowledge_runtime_sha256 == second.knowledge_runtime_sha256
    assert first.knowledge_validation_report_sha256 != second.knowledge_validation_report_sha256
    assert first.content_hash != second.content_hash


def test_explicit_release_pin_never_falls_forward_and_next_cycle_may_select_another_release(
    tmp_path, ring, templates
):
    store = KnowledgeArtifactStore(tmp_path)
    first_stored, _, first_report, first_active = _publish_active(store, _bundle())
    first_before = _enrich(store, ring, templates, first_stored, first_report, first_active)

    second_stored, _, second_report, second_active = _publish_active(
        store,
        _bundle(version="1.1.0", title_suffix=" v1.1"),
    )
    first_after = _enrich(store, ring, templates, first_stored, first_report, first_active)
    second = _enrich(store, ring, templates, second_stored, second_report, second_active)

    assert first_before == first_after
    assert first_after.knowledge_artifact_version == "1.0.0"
    assert second.knowledge_artifact_version == "1.1.0"
    assert second.knowledge_runtime_sha256 == second_active.runtime_sha256
    assert second.knowledge_runtime_sha256 != first_after.knowledge_runtime_sha256

    absent_runtime, _ = compile_knowledge_library(_bundle(version="9.9.9"))
    absent_report = _report(absent_runtime)
    absent_active = promote_knowledge_runtime(absent_runtime, absent_report)
    with pytest.raises(KnowledgeArtifactStorageError, match="missing files"):
        enrich_prompt_with_active_release(
            ring,
            templates,
            store,
            knowledge_package_id=absent_active.package_id,
            knowledge_artifact_version="9.9.9",
            active_release=absent_active,
            validation_report=absent_report,
        )
