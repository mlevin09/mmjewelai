"""Read-only technical readiness assessment for controlled Prompt Enrichment rollout."""

import argparse
import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from jewelai_domain import (
    KnowledgeReleaseCandidateKind,
    KnowledgeReleaseQualification,
    KnowledgeReleaseQualificationStatus,
)
from jewelai_domain.models import ImmutableModel
from jewelai_prompts import (
    FINAL_PROMPT_SCHEMA_VERSION,
    INTERNAL_FINAL_PROMPT_HANDOFF_SCHEMA_VERSION,
)
from pydantic import StringConstraints, model_validator

from .prompt_enrichment_composition import PROMPT_ENRICHMENT_RUNTIME_COMPOSITION_VERSION

PROMPT_ENRICHMENT_RELEASE_READINESS_VERSION = "1.0.0"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceCommit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
EvidenceReference = Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")]
Detail = Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class PromptEnrichmentReadinessOutcome(StrEnum):
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    BLOCKED = "BLOCKED"
    NOT_EVALUATED = "NOT_EVALUATED"


class PromptEnrichmentReadinessGateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class PromptEnrichmentEvidenceKind(StrEnum):
    REAL = "REAL"
    SYNTHETIC = "SYNTHETIC"
    NONE = "NONE"


class PromptEnrichmentReadinessReasonCode(StrEnum):
    VERIFIED = "verified"
    VERIFIED_FAILURE = "verified_failure"
    EVIDENCE_MISSING = "evidence_missing"
    REAL_CATALOG_NOT_EVALUATED = "real_catalog_not_evaluated"
    SYNTHETIC_EVIDENCE_ONLY = "synthetic_evidence_only"
    KNOWLEDGE_QUALIFICATION_BLOCKED = "knowledge_qualification_blocked"
    OPERATIONAL_APPROVAL_REQUIRED = "operational_approval_required"


class PromptEnrichmentReadinessGateId(StrEnum):
    SOURCE_INTEGRITY = "source_integrity"
    REAL_CATALOG = "real_catalog"
    KNOWLEDGE_VALIDATION = "knowledge_validation"
    ACTIVE_INTEGRITY = "active_integrity"
    DURABLE_STORAGE = "durable_storage"
    RUNTIME_COMPOSITION = "runtime_composition"
    DEFAULT_ISOLATION = "default_isolation"
    MIGRATION_REHEARSAL = "migration_rehearsal"
    ROLLBACK_REHEARSAL = "rollback_rehearsal"
    AUTHENTICATION = "authentication"
    SEMANTIC_CORRECTNESS = "semantic_correctness"
    CONSTRAINT_PRESERVATION = "constraint_preservation"
    FINAL_PROMPT = "final_prompt"
    HANDOFF = "handoff"
    LEGACY_ISOLATION = "legacy_isolation"
    OBSERVABILITY = "observability"
    OPERATIONAL_APPROVAL = "operational_approval"


KNOWLEDGE_READINESS_GATES = frozenset(
    {
        PromptEnrichmentReadinessGateId.REAL_CATALOG,
        PromptEnrichmentReadinessGateId.KNOWLEDGE_VALIDATION,
        PromptEnrichmentReadinessGateId.ACTIVE_INTEGRITY,
        PromptEnrichmentReadinessGateId.DURABLE_STORAGE,
    }
)
OPTIONAL_READINESS_GATES = frozenset({PromptEnrichmentReadinessGateId.OPERATIONAL_APPROVAL})


class PromptEnrichmentReadinessGate(ImmutableModel):
    gate: PromptEnrichmentReadinessGateId
    status: PromptEnrichmentReadinessGateStatus
    evidence_kind: PromptEnrichmentEvidenceKind
    verified_directly: bool
    evidence_references: tuple[EvidenceReference, ...] = ()
    reason_code: PromptEnrichmentReadinessReasonCode
    detail: Detail

    @model_validator(mode="after")
    def validate_evidence(self):
        if len(set(self.evidence_references)) != len(self.evidence_references):
            raise ValueError("readiness evidence references must be unique")
        if tuple(sorted(self.evidence_references)) != self.evidence_references:
            raise ValueError("readiness evidence references must use stable order")
        if self.status == PromptEnrichmentReadinessGateStatus.PASS:
            if (
                not self.verified_directly
                or self.evidence_kind == PromptEnrichmentEvidenceKind.NONE
                or not self.evidence_references
                or self.reason_code != PromptEnrichmentReadinessReasonCode.VERIFIED
            ):
                raise ValueError("passing readiness gate requires verified evidence")
        if self.status == PromptEnrichmentReadinessGateStatus.FAIL:
            if (
                not self.verified_directly
                or not self.evidence_references
                or self.reason_code
                not in {
                    PromptEnrichmentReadinessReasonCode.VERIFIED_FAILURE,
                    PromptEnrichmentReadinessReasonCode.KNOWLEDGE_QUALIFICATION_BLOCKED,
                }
            ):
                raise ValueError("failed readiness gate requires verified blocking evidence")
        if (
            self.status == PromptEnrichmentReadinessGateStatus.NOT_EVALUATED
            and self.reason_code
            in {
                PromptEnrichmentReadinessReasonCode.VERIFIED,
                PromptEnrichmentReadinessReasonCode.VERIFIED_FAILURE,
                PromptEnrichmentReadinessReasonCode.KNOWLEDGE_QUALIFICATION_BLOCKED,
            }
        ):
            raise ValueError("unevaluated readiness gate cannot claim a verified result")
        return self


class PromptEnrichmentReadinessIssue(ImmutableModel):
    gate: PromptEnrichmentReadinessGateId
    reason_code: PromptEnrichmentReadinessReasonCode
    detail: Detail


class PromptEnrichmentReleaseReadinessAssessment(ImmutableModel):
    assessment_schema_version: Literal["1.0.0"] = PROMPT_ENRICHMENT_RELEASE_READINESS_VERSION
    outcome: PromptEnrichmentReadinessOutcome
    source_commit: SourceCommit
    knowledge_candidate_kind: KnowledgeReleaseCandidateKind | None = None
    knowledge_package_id: str | None = None
    knowledge_artifact_version: str | None = None
    knowledge_runtime_sha256: Sha256 | None = None
    knowledge_validation_report_sha256: Sha256 | None = None
    knowledge_qualification_outcome: KnowledgeReleaseQualificationStatus | None = None
    knowledge_qualification_sha256: Sha256 | None = None
    runtime_composition_contract_version: Literal["1.0.0"] = (
        PROMPT_ENRICHMENT_RUNTIME_COMPOSITION_VERSION
    )
    internal_final_prompt_schema_version: Literal["1.1.0"] = FINAL_PROMPT_SCHEMA_VERSION
    handoff_schema_version: Literal["1.0.0"] = INTERNAL_FINAL_PROMPT_HANDOFF_SCHEMA_VERSION
    migration_head: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}_[a-z0-9_]+$")]
    gates: tuple[PromptEnrichmentReadinessGate, ...]
    missing_evidence: tuple[PromptEnrichmentReadinessIssue, ...]
    blocking_reasons: tuple[PromptEnrichmentReadinessIssue, ...]
    canonical_evidence_hash: Sha256

    @model_validator(mode="after")
    def validate_assessment(self):
        expected_order = tuple(PromptEnrichmentReadinessGateId)
        if tuple(item.gate for item in self.gates) != expected_order:
            raise ValueError("readiness assessment must contain every gate in canonical order")
        if len({item.gate for item in self.gates}) != len(self.gates):
            raise ValueError("readiness assessment gates must be unique")
        expected_missing, expected_blocking, expected_outcome = _aggregate(self.gates)
        if self.missing_evidence != expected_missing:
            raise ValueError("readiness missing-evidence summary mismatch")
        if self.blocking_reasons != expected_blocking:
            raise ValueError("readiness blocking-reason summary mismatch")
        if self.outcome != expected_outcome:
            raise ValueError("readiness outcome does not match mandatory gates")
        knowledge = tuple(item for item in self.gates if item.gate in KNOWLEDGE_READINESS_GATES)
        if any(item.status == PromptEnrichmentReadinessGateStatus.PASS for item in knowledge):
            if (
                not all(
                    item.status == PromptEnrichmentReadinessGateStatus.PASS for item in knowledge
                )
                or self.knowledge_candidate_kind
                != KnowledgeReleaseCandidateKind.PRODUCTION_INTENDED
                or self.knowledge_qualification_outcome
                != KnowledgeReleaseQualificationStatus.QUALIFIED
                or not all(
                    (
                        self.knowledge_package_id,
                        self.knowledge_artifact_version,
                        self.knowledge_runtime_sha256,
                        self.knowledge_validation_report_sha256,
                        self.knowledge_qualification_sha256,
                    )
                )
            ):
                raise ValueError(
                    "passing Knowledge gates require complete qualified release evidence"
                )
        if self.knowledge_qualification_outcome == KnowledgeReleaseQualificationStatus.QUALIFIED:
            if not all(
                (
                    self.knowledge_candidate_kind,
                    self.knowledge_package_id,
                    self.knowledge_artifact_version,
                    self.knowledge_runtime_sha256,
                    self.knowledge_validation_report_sha256,
                    self.knowledge_qualification_sha256,
                )
            ):
                raise ValueError("qualified Knowledge evidence identity must be complete")
        payload = self.model_dump(mode="json", exclude={"canonical_evidence_hash"})
        if self.canonical_evidence_hash != _hash(payload):
            raise ValueError("readiness canonical evidence hash mismatch")
        return self

    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="json"))


def assess_prompt_enrichment_release_readiness(
    *,
    source_commit: str,
    migration_head: str,
    qualification: KnowledgeReleaseQualification | object | None,
    gates: tuple[PromptEnrichmentReadinessGate, ...],
) -> PromptEnrichmentReleaseReadinessAssessment:
    """Aggregate explicit evidence without activating, publishing, or selecting a release."""

    validated_qualification = (
        KnowledgeReleaseQualification.model_validate(qualification)
        if qualification is not None
        else None
    )
    if (
        validated_qualification is not None
        and validated_qualification.source_commit is not None
        and validated_qualification.source_commit != source_commit
    ):
        raise ValueError("knowledge qualification source commit does not match assessment")

    supplied = tuple(PromptEnrichmentReadinessGate.model_validate(item) for item in gates)
    supplied_ids = tuple(item.gate for item in supplied)
    expected_supplied = tuple(
        gate for gate in PromptEnrichmentReadinessGateId if gate not in KNOWLEDGE_READINESS_GATES
    )
    if supplied_ids != expected_supplied:
        raise ValueError("caller-supplied readiness gates must use canonical non-Knowledge order")

    knowledge_gates = _knowledge_gates(validated_qualification)
    by_id = {item.gate: item for item in (*supplied, *knowledge_gates)}
    ordered = tuple(by_id[gate] for gate in PromptEnrichmentReadinessGateId)
    missing, blockers, outcome = _aggregate(ordered)
    values = {
        "assessment_schema_version": PROMPT_ENRICHMENT_RELEASE_READINESS_VERSION,
        "outcome": outcome,
        "source_commit": source_commit,
        "knowledge_candidate_kind": (
            validated_qualification.candidate_kind if validated_qualification else None
        ),
        "knowledge_package_id": (
            validated_qualification.package_id if validated_qualification else None
        ),
        "knowledge_artifact_version": (
            validated_qualification.artifact_version if validated_qualification else None
        ),
        "knowledge_runtime_sha256": (
            validated_qualification.runtime_sha256 if validated_qualification else None
        ),
        "knowledge_validation_report_sha256": (
            validated_qualification.validation_report_sha256 if validated_qualification else None
        ),
        "knowledge_qualification_outcome": (
            validated_qualification.status if validated_qualification else None
        ),
        "knowledge_qualification_sha256": (
            validated_qualification.qualification_sha256 if validated_qualification else None
        ),
        "runtime_composition_contract_version": PROMPT_ENRICHMENT_RUNTIME_COMPOSITION_VERSION,
        "internal_final_prompt_schema_version": FINAL_PROMPT_SCHEMA_VERSION,
        "handoff_schema_version": INTERNAL_FINAL_PROMPT_HANDOFF_SCHEMA_VERSION,
        "migration_head": migration_head,
        "gates": ordered,
        "missing_evidence": missing,
        "blocking_reasons": blockers,
    }
    payload = _json(values)
    return PromptEnrichmentReleaseReadinessAssessment(
        **values,
        canonical_evidence_hash=_hash(payload),
    )


def _knowledge_gates(
    qualification: KnowledgeReleaseQualification | None,
) -> tuple[PromptEnrichmentReadinessGate, ...]:
    if (
        qualification is None
        or qualification.status == KnowledgeReleaseQualificationStatus.NOT_EVALUATED
    ):
        reference = (
            (f"qualification://{qualification.qualification_sha256}",) if qualification else ()
        )
        return tuple(
            PromptEnrichmentReadinessGate(
                gate=gate,
                status=PromptEnrichmentReadinessGateStatus.NOT_EVALUATED,
                evidence_kind=PromptEnrichmentEvidenceKind.NONE,
                verified_directly=qualification is not None,
                evidence_references=reference,
                reason_code=PromptEnrichmentReadinessReasonCode.REAL_CATALOG_NOT_EVALUATED,
                detail="No real production-intended Knowledge release was evaluated.",
            )
            for gate in PromptEnrichmentReadinessGateId
            if gate in KNOWLEDGE_READINESS_GATES
        )
    if qualification.status == KnowledgeReleaseQualificationStatus.BLOCKED:
        detail = ", ".join(item.code.value for item in qualification.blockers)
        kind = (
            PromptEnrichmentEvidenceKind.REAL
            if qualification.candidate_kind == KnowledgeReleaseCandidateKind.PRODUCTION_INTENDED
            else PromptEnrichmentEvidenceKind.SYNTHETIC
            if qualification.candidate_kind == KnowledgeReleaseCandidateKind.SYNTHETIC
            else PromptEnrichmentEvidenceKind.NONE
        )
        return tuple(
            PromptEnrichmentReadinessGate(
                gate=gate,
                status=PromptEnrichmentReadinessGateStatus.FAIL,
                evidence_kind=kind,
                verified_directly=True,
                evidence_references=(f"qualification://{qualification.qualification_sha256}",),
                reason_code=(PromptEnrichmentReadinessReasonCode.KNOWLEDGE_QUALIFICATION_BLOCKED),
                detail=f"Knowledge release qualification blocked: {detail}.",
            )
            for gate in PromptEnrichmentReadinessGateId
            if gate in KNOWLEDGE_READINESS_GATES
        )
    if qualification.candidate_kind == KnowledgeReleaseCandidateKind.SYNTHETIC:
        return tuple(
            PromptEnrichmentReadinessGate(
                gate=gate,
                status=PromptEnrichmentReadinessGateStatus.NOT_EVALUATED,
                evidence_kind=PromptEnrichmentEvidenceKind.SYNTHETIC,
                verified_directly=True,
                evidence_references=(f"qualification://{qualification.qualification_sha256}",),
                reason_code=PromptEnrichmentReadinessReasonCode.SYNTHETIC_EVIDENCE_ONLY,
                detail="Synthetic qualification cannot establish real-catalog readiness.",
            )
            for gate in PromptEnrichmentReadinessGateId
            if gate in KNOWLEDGE_READINESS_GATES
        )
    return tuple(
        PromptEnrichmentReadinessGate(
            gate=gate,
            status=PromptEnrichmentReadinessGateStatus.PASS,
            evidence_kind=PromptEnrichmentEvidenceKind.REAL,
            verified_directly=True,
            evidence_references=(f"qualification://{qualification.qualification_sha256}",),
            reason_code=PromptEnrichmentReadinessReasonCode.VERIFIED,
            detail="Exact production-intended Knowledge release qualified through contract v1.0.0.",
        )
        for gate in PromptEnrichmentReadinessGateId
        if gate in KNOWLEDGE_READINESS_GATES
    )


def _aggregate(
    gates: tuple[PromptEnrichmentReadinessGate, ...],
) -> tuple[
    tuple[PromptEnrichmentReadinessIssue, ...],
    tuple[PromptEnrichmentReadinessIssue, ...],
    PromptEnrichmentReadinessOutcome,
]:
    missing = tuple(
        PromptEnrichmentReadinessIssue(
            gate=item.gate, reason_code=item.reason_code, detail=item.detail
        )
        for item in gates
        if item.status == PromptEnrichmentReadinessGateStatus.NOT_EVALUATED
    )
    blockers = tuple(
        PromptEnrichmentReadinessIssue(
            gate=item.gate, reason_code=item.reason_code, detail=item.detail
        )
        for item in gates
        if item.status == PromptEnrichmentReadinessGateStatus.FAIL
    )
    mandatory = tuple(item for item in gates if item.gate not in OPTIONAL_READINESS_GATES)
    if any(item.status == PromptEnrichmentReadinessGateStatus.FAIL for item in mandatory):
        outcome = PromptEnrichmentReadinessOutcome.BLOCKED
    elif any(
        item.status == PromptEnrichmentReadinessGateStatus.NOT_EVALUATED for item in mandatory
    ):
        outcome = PromptEnrichmentReadinessOutcome.NOT_EVALUATED
    else:
        outcome = PromptEnrichmentReadinessOutcome.READY_FOR_APPROVAL
    return missing, blockers, outcome


def _json(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: str | None) -> object | None:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--migration-head", required=True)
    parser.add_argument("--qualification")
    parser.add_argument("--gates", required=True)
    args = parser.parse_args(argv)
    gate_payload = _read_json(args.gates)
    if not isinstance(gate_payload, list):
        parser.error("--gates must contain a JSON array")
    assessment = assess_prompt_enrichment_release_readiness(
        source_commit=args.source_commit,
        migration_head=args.migration_head,
        qualification=_read_json(args.qualification),
        gates=tuple(PromptEnrichmentReadinessGate.model_validate(item) for item in gate_payload),
    )
    print(assessment.canonical_json())
    return {
        PromptEnrichmentReadinessOutcome.READY_FOR_APPROVAL: 0,
        PromptEnrichmentReadinessOutcome.BLOCKED: 1,
        PromptEnrichmentReadinessOutcome.NOT_EVALUATED: 2,
    }[assessment.outcome]


if __name__ == "__main__":
    raise SystemExit(main())
