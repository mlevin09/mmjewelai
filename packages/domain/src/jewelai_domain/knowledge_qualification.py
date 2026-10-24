"""Read-only qualification of explicitly selected Knowledge Library releases."""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import StringConstraints, ValidationError, model_validator

from .knowledge_activation import (
    ActiveKnowledgeRuntime,
    ProductionValidationReport,
    ProductionValidationStatus,
    Sha256,
)
from .knowledge_storage import KnowledgeArtifactStorageError, KnowledgeArtifactStore
from .models import ImmutableModel, Version

KNOWLEDGE_RELEASE_QUALIFICATION_VERSION = "1.0.0"

PackageId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]+$")]
SourceCommit = Annotated[
    str,
    StringConstraints(min_length=7, max_length=64, pattern=r"^[0-9a-f]+$"),
]


class KnowledgeReleaseQualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    BLOCKED = "BLOCKED"
    NOT_EVALUATED = "NOT_EVALUATED"


class KnowledgeReleaseCandidateKind(StrEnum):
    PRODUCTION_INTENDED = "PRODUCTION_INTENDED"
    SYNTHETIC = "SYNTHETIC"


class KnowledgeReleaseQualificationBlockerCode(StrEnum):
    CANDIDATE_NOT_SUPPLIED = "candidate_not_supplied"
    CANDIDATE_INVALID = "candidate_invalid"
    ACTIVE_ENVELOPE_MISSING = "active_envelope_missing"
    ACTIVE_ENVELOPE_INVALID = "active_envelope_invalid"
    VALIDATION_REPORT_MISSING = "validation_report_missing"
    VALIDATION_REPORT_INVALID = "validation_report_invalid"
    VALIDATION_GATE_BLOCKED = "validation_gate_blocked"
    RUNTIME_VERIFICATION_FAILED = "runtime_verification_failed"


class KnowledgeReleaseCandidateSelection(ImmutableModel):
    package_id: PackageId
    artifact_version: Version
    kind: KnowledgeReleaseCandidateKind = KnowledgeReleaseCandidateKind.PRODUCTION_INTENDED


class KnowledgeReleaseQualificationBlocker(ImmutableModel):
    code: KnowledgeReleaseQualificationBlockerCode
    detail: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class KnowledgeReleaseQualification(ImmutableModel):
    qualification_contract_version: Literal["1.0.0"] = KNOWLEDGE_RELEASE_QUALIFICATION_VERSION
    status: KnowledgeReleaseQualificationStatus
    candidate_kind: KnowledgeReleaseCandidateKind | None = None
    package_id: str | None = None
    artifact_version: str | None = None
    runtime_sha256: Sha256 | None = None
    validation_report_sha256: Sha256 | None = None
    validation_gate_status: ProductionValidationStatus | None = None
    runtime_loader_compatible: bool = False
    source_commit: SourceCommit | None = None
    blockers: tuple[KnowledgeReleaseQualificationBlocker, ...] = ()
    qualification_sha256: Sha256

    @model_validator(mode="after")
    def validate_result(self):
        payload = self.model_dump(mode="json", exclude={"qualification_sha256"})
        if self.qualification_sha256 != _hash(payload):
            raise ValueError("knowledge release qualification hash mismatch")
        if self.status == KnowledgeReleaseQualificationStatus.QUALIFIED:
            if self.blockers:
                raise ValueError("qualified release cannot contain blockers")
            if not self.runtime_loader_compatible:
                raise ValueError("qualified release must be runtime-load compatible")
            if self.validation_gate_status != ProductionValidationStatus.ELIGIBLE:
                raise ValueError("qualified release must have eligible validation evidence")
            if not all(
                (
                    self.candidate_kind,
                    self.package_id,
                    self.artifact_version,
                    self.runtime_sha256,
                    self.validation_report_sha256,
                )
            ):
                raise ValueError("qualified release identity must be complete")
        elif not self.blockers:
            raise ValueError("non-qualified release must explain why it did not qualify")
        return self

    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="json"))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _result(**values) -> KnowledgeReleaseQualification:
    payload = {
        "qualification_contract_version": KNOWLEDGE_RELEASE_QUALIFICATION_VERSION,
        **values,
    }
    draft = KnowledgeReleaseQualification.model_construct(
        **payload,
        qualification_sha256="0" * 64,
    )
    canonical_payload = draft.model_dump(mode="json", exclude={"qualification_sha256"})
    return KnowledgeReleaseQualification(
        **canonical_payload,
        qualification_sha256=_hash(canonical_payload),
    )


def _blocked(
    selection: KnowledgeReleaseCandidateSelection | None,
    blocker: KnowledgeReleaseQualificationBlocker,
    *,
    source_commit: str | None,
    validation_report: ProductionValidationReport | None = None,
) -> KnowledgeReleaseQualification:
    return _result(
        status=KnowledgeReleaseQualificationStatus.BLOCKED,
        candidate_kind=selection.kind if selection else None,
        package_id=selection.package_id if selection else None,
        artifact_version=selection.artifact_version if selection else None,
        runtime_sha256=validation_report.runtime_sha256 if validation_report else None,
        validation_report_sha256=validation_report.sha256 if validation_report else None,
        validation_gate_status=validation_report.status if validation_report else None,
        runtime_loader_compatible=False,
        source_commit=source_commit,
        blockers=(blocker,),
    )


def qualify_knowledge_release(
    artifact_store: KnowledgeArtifactStore,
    selection: KnowledgeReleaseCandidateSelection | object | None,
    *,
    active_release: ActiveKnowledgeRuntime | object | None = None,
    validation_report: ProductionValidationReport | object | None = None,
    source_commit: str | None = None,
) -> KnowledgeReleaseQualification:
    """Qualify one immutable candidate without publishing, promoting, or selecting it.

    A ``QUALIFIED`` synthetic candidate proves only that the mechanism and fixture are compatible;
    it is never evidence that a real production-intended release has been evaluated or activated.
    """

    if selection is None:
        return _result(
            status=KnowledgeReleaseQualificationStatus.NOT_EVALUATED,
            candidate_kind=None,
            package_id=None,
            artifact_version=None,
            runtime_sha256=None,
            validation_report_sha256=None,
            validation_gate_status=None,
            runtime_loader_compatible=False,
            source_commit=source_commit,
            blockers=(
                KnowledgeReleaseQualificationBlocker(
                    code=KnowledgeReleaseQualificationBlockerCode.CANDIDATE_NOT_SUPPLIED,
                    detail="No Knowledge Library release candidate was supplied.",
                ),
            ),
        )

    try:
        selected = KnowledgeReleaseCandidateSelection.model_validate(selection)
    except ValidationError:
        return _blocked(
            None,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.CANDIDATE_INVALID,
                detail="The selected Knowledge Library release identity is invalid.",
            ),
            source_commit=source_commit,
        )

    if active_release is None:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.ACTIVE_ENVELOPE_MISSING,
                detail="The selected release has no ACTIVE envelope.",
            ),
            source_commit=source_commit,
        )
    try:
        active = ActiveKnowledgeRuntime.model_validate(active_release)
    except ValidationError:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.ACTIVE_ENVELOPE_INVALID,
                detail="The selected release ACTIVE envelope is invalid or unsupported.",
            ),
            source_commit=source_commit,
        )

    if validation_report is None:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.VALIDATION_REPORT_MISSING,
                detail="The selected release has no production validation report.",
            ),
            source_commit=source_commit,
        )
    try:
        report = ProductionValidationReport.model_validate(validation_report)
    except ValidationError:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.VALIDATION_REPORT_INVALID,
                detail=(
                    "The selected release production validation report is invalid or unsupported."
                ),
            ),
            source_commit=source_commit,
        )

    if report.status != ProductionValidationStatus.ELIGIBLE:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.VALIDATION_GATE_BLOCKED,
                detail=f"Production validation gate status is {report.status.value}.",
            ),
            source_commit=source_commit,
            validation_report=report,
        )

    try:
        verified = artifact_store.load_active_runtime(
            selected.package_id,
            selected.artifact_version,
            active_release=active,
            validation_report=report,
        )
    except KnowledgeArtifactStorageError as exc:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.RUNTIME_VERIFICATION_FAILED,
                detail=str(exc),
            ),
            source_commit=source_commit,
            validation_report=report,
        )

    return _result(
        status=KnowledgeReleaseQualificationStatus.QUALIFIED,
        candidate_kind=selected.kind,
        package_id=verified.package_id,
        artifact_version=str(verified.artifact_version),
        runtime_sha256=verified.runtime_sha256,
        validation_report_sha256=verified.validation_report_sha256,
        validation_gate_status=report.status,
        runtime_loader_compatible=True,
        source_commit=source_commit,
        blockers=(),
    )
