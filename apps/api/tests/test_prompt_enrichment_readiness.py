import json
from pathlib import Path

import pytest
from jewelai_domain import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    KnowledgeArtifactStore,
    KnowledgeReleaseCandidateKind,
    KnowledgeReleaseCandidateSelection,
    ProductionValidationCheck,
    ProductionValidationReport,
    compile_knowledge_library,
    promote_knowledge_runtime,
    qualify_knowledge_release,
)
from pydantic import ValidationError

from jewelai_api.prompt_enrichment_readiness import (
    KNOWLEDGE_READINESS_GATES,
    PromptEnrichmentEvidenceKind,
    PromptEnrichmentReadinessGate,
    PromptEnrichmentReadinessGateId,
    PromptEnrichmentReadinessGateStatus,
    PromptEnrichmentReadinessOutcome,
    PromptEnrichmentReadinessReasonCode,
    PromptEnrichmentReleaseReadinessAssessment,
    assess_prompt_enrichment_release_readiness,
    main,
)

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "data" / "knowledge" / "v1" / "three-stone-1.0.0.json"
SOURCE_COMMIT = "f1769bab181282fa6a9089a2bf89c666bb043656"


def _qualification(tmp_path, kind):
    bundle = json.loads(PACKAGE.read_text(encoding="utf-8"))
    store = KnowledgeArtifactStore(tmp_path / "knowledge")
    stored = store.publish(bundle)
    runtime, _ = compile_knowledge_library(bundle)
    report = ProductionValidationReport(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome="PASS",
                evidence_ref=f"synthetic://{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )
    active = promote_knowledge_runtime(runtime, report)
    return qualify_knowledge_release(
        store,
        KnowledgeReleaseCandidateSelection(
            package_id=stored.package_id,
            artifact_version=stored.artifact_version,
            kind=kind,
        ),
        active_release=active,
        validation_report=report,
        source_commit=SOURCE_COMMIT,
    )


def _non_knowledge_gates(*, status=PromptEnrichmentReadinessGateStatus.PASS):
    gates = []
    for gate in PromptEnrichmentReadinessGateId:
        if gate in KNOWLEDGE_READINESS_GATES:
            continue
        if gate == PromptEnrichmentReadinessGateId.OPERATIONAL_APPROVAL:
            gates.append(
                PromptEnrichmentReadinessGate(
                    gate=gate,
                    status=PromptEnrichmentReadinessGateStatus.NOT_EVALUATED,
                    evidence_kind=PromptEnrichmentEvidenceKind.NONE,
                    verified_directly=False,
                    reason_code=(PromptEnrichmentReadinessReasonCode.OPERATIONAL_APPROVAL_REQUIRED),
                    detail="An accountable release decision has not been recorded.",
                )
            )
            continue
        gates.append(
            PromptEnrichmentReadinessGate(
                gate=gate,
                status=status,
                evidence_kind=PromptEnrichmentEvidenceKind.SYNTHETIC,
                verified_directly=status != PromptEnrichmentReadinessGateStatus.NOT_EVALUATED,
                evidence_references=(f"test://{gate.value}",)
                if status != PromptEnrichmentReadinessGateStatus.NOT_EVALUATED
                else (),
                reason_code=(
                    PromptEnrichmentReadinessReasonCode.VERIFIED
                    if status == PromptEnrichmentReadinessGateStatus.PASS
                    else PromptEnrichmentReadinessReasonCode.VERIFIED_FAILURE
                    if status == PromptEnrichmentReadinessGateStatus.FAIL
                    else PromptEnrichmentReadinessReasonCode.EVIDENCE_MISSING
                ),
                detail=f"Test evidence for {gate.value}.",
            )
        )
    return tuple(gates)


def test_complete_real_evidence_is_deterministic_and_ready_for_human_approval(tmp_path):
    qualification = _qualification(tmp_path, KnowledgeReleaseCandidateKind.PRODUCTION_INTENDED)

    first = assess_prompt_enrichment_release_readiness(
        source_commit=SOURCE_COMMIT,
        migration_head="0014_clarification_plans",
        qualification=qualification,
        gates=_non_knowledge_gates(),
    )
    second = assess_prompt_enrichment_release_readiness(
        source_commit=SOURCE_COMMIT,
        migration_head="0014_clarification_plans",
        qualification=qualification,
        gates=_non_knowledge_gates(),
    )

    assert first == second
    assert first.outcome == PromptEnrichmentReadinessOutcome.READY_FOR_APPROVAL
    assert first.blocking_reasons == ()
    assert tuple(item.gate for item in first.missing_evidence) == (
        PromptEnrichmentReadinessGateId.OPERATIONAL_APPROVAL,
    )
    assert len(first.canonical_evidence_hash) == 64
    assert "decision_date" not in PromptEnrichmentReleaseReadinessAssessment.model_fields


def test_synthetic_qualification_never_establishes_real_catalog_readiness(tmp_path):
    assessment = assess_prompt_enrichment_release_readiness(
        source_commit=SOURCE_COMMIT,
        migration_head="0014_clarification_plans",
        qualification=_qualification(tmp_path, KnowledgeReleaseCandidateKind.SYNTHETIC),
        gates=_non_knowledge_gates(),
    )

    assert assessment.outcome == PromptEnrichmentReadinessOutcome.NOT_EVALUATED
    knowledge = tuple(item for item in assessment.gates if item.gate in KNOWLEDGE_READINESS_GATES)
    assert all(
        item.status == PromptEnrichmentReadinessGateStatus.NOT_EVALUATED for item in knowledge
    )
    assert all(item.evidence_kind == PromptEnrichmentEvidenceKind.SYNTHETIC for item in knowledge)
    assert all(
        item.reason_code == PromptEnrichmentReadinessReasonCode.SYNTHETIC_EVIDENCE_ONLY
        for item in knowledge
    )


def test_missing_real_catalog_is_explicitly_not_evaluated():
    assessment = assess_prompt_enrichment_release_readiness(
        source_commit=SOURCE_COMMIT,
        migration_head="0014_clarification_plans",
        qualification=None,
        gates=_non_knowledge_gates(),
    )

    assert assessment.outcome == PromptEnrichmentReadinessOutcome.NOT_EVALUATED
    assert assessment.knowledge_qualification_outcome is None
    assert (
        next(
            item
            for item in assessment.gates
            if item.gate == PromptEnrichmentReadinessGateId.REAL_CATALOG
        ).reason_code
        == PromptEnrichmentReadinessReasonCode.REAL_CATALOG_NOT_EVALUATED
    )


def test_verified_failure_precedes_missing_evidence_and_optional_approval_cannot_override(tmp_path):
    gates = list(_non_knowledge_gates())
    index = next(
        index
        for index, item in enumerate(gates)
        if item.gate == PromptEnrichmentReadinessGateId.MIGRATION_REHEARSAL
    )
    gates[index] = PromptEnrichmentReadinessGate(
        gate=PromptEnrichmentReadinessGateId.MIGRATION_REHEARSAL,
        status=PromptEnrichmentReadinessGateStatus.FAIL,
        evidence_kind=PromptEnrichmentEvidenceKind.REAL,
        verified_directly=True,
        evidence_references=("ci://postgres/migration-rehearsal",),
        reason_code=PromptEnrichmentReadinessReasonCode.VERIFIED_FAILURE,
        detail="Disposable PostgreSQL migration rehearsal failed.",
    )

    assessment = assess_prompt_enrichment_release_readiness(
        source_commit=SOURCE_COMMIT,
        migration_head="0014_clarification_plans",
        qualification=_qualification(tmp_path, KnowledgeReleaseCandidateKind.SYNTHETIC),
        gates=tuple(gates),
    )

    assert assessment.outcome == PromptEnrichmentReadinessOutcome.BLOCKED
    assert assessment.blocking_reasons[0].gate == (
        PromptEnrichmentReadinessGateId.MIGRATION_REHEARSAL
    )
    assert assessment.missing_evidence


def test_gate_contract_and_assessment_hash_fail_closed(tmp_path):
    with pytest.raises(ValidationError, match="passing readiness gate requires verified evidence"):
        PromptEnrichmentReadinessGate(
            gate=PromptEnrichmentReadinessGateId.SOURCE_INTEGRITY,
            status=PromptEnrichmentReadinessGateStatus.PASS,
            evidence_kind=PromptEnrichmentEvidenceKind.NONE,
            verified_directly=False,
            reason_code=PromptEnrichmentReadinessReasonCode.VERIFIED,
            detail="Unverified claim.",
        )

    assessment = assess_prompt_enrichment_release_readiness(
        source_commit=SOURCE_COMMIT,
        migration_head="0014_clarification_plans",
        qualification=_qualification(tmp_path, KnowledgeReleaseCandidateKind.SYNTHETIC),
        gates=_non_knowledge_gates(),
    )
    tampered = assessment.model_dump(mode="json")
    tampered["migration_head"] = "9999_tampered"
    with pytest.raises(ValidationError, match="canonical evidence hash mismatch"):
        PromptEnrichmentReleaseReadinessAssessment.model_validate(tampered)


def test_qualification_source_commit_must_match_assessment(tmp_path):
    with pytest.raises(ValueError, match="source commit does not match"):
        assess_prompt_enrichment_release_readiness(
            source_commit="0" * 40,
            migration_head="0014_clarification_plans",
            qualification=_qualification(tmp_path, KnowledgeReleaseCandidateKind.SYNTHETIC),
            gates=_non_knowledge_gates(),
        )


def test_read_only_cli_reports_incomplete_evidence_and_exits_nonzero(tmp_path, capsys):
    gates_path = tmp_path / "gates.json"
    gates_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in _non_knowledge_gates()]),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--source-commit",
            SOURCE_COMMIT,
            "--migration-head",
            "0014_clarification_plans",
            "--gates",
            str(gates_path),
        ]
    )

    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["outcome"] == "NOT_EVALUATED"
    assert output["knowledge_package_id"] is None
    assert output["canonical_evidence_hash"]
