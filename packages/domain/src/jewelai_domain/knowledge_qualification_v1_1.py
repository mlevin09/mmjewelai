"""Read-only qualification for explicitly selected Knowledge Library v1.1 releases."""

from pydantic import ValidationError

from .knowledge_activation import ProductionValidationStatus
from .knowledge_activation_v1_1 import (
    ActiveKnowledgeRuntimeV1_1,
    ProductionValidationReportV1_1,
)
from .knowledge_qualification import (
    KnowledgeReleaseCandidateSelection,
    KnowledgeReleaseQualification,
    KnowledgeReleaseQualificationBlocker,
    KnowledgeReleaseQualificationBlockerCode,
    KnowledgeReleaseQualificationStatus,
    _blocked,
    _result,
)
from .knowledge_storage import KnowledgeArtifactStorageError
from .knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1


def qualify_knowledge_release_v1_1(
    artifact_store: KnowledgeArtifactStoreV1_1,
    selection: KnowledgeReleaseCandidateSelection | object | None,
    *,
    active_release: ActiveKnowledgeRuntimeV1_1 | object | None = None,
    validation_report: ProductionValidationReportV1_1 | object | None = None,
    source_commit: str | None = None,
) -> KnowledgeReleaseQualification:
    """Qualify one immutable v1.1 candidate without publishing or selecting it."""

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
                    detail="No Knowledge Library v1.1 release candidate was supplied.",
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
                detail="The selected Knowledge Library v1.1 release identity is invalid.",
            ),
            source_commit=source_commit,
        )

    if active_release is None:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.ACTIVE_ENVELOPE_MISSING,
                detail="The selected v1.1 release has no ACTIVE envelope.",
            ),
            source_commit=source_commit,
        )
    try:
        active = ActiveKnowledgeRuntimeV1_1.model_validate(active_release)
    except ValidationError:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.ACTIVE_ENVELOPE_INVALID,
                detail="The selected v1.1 ACTIVE envelope is invalid or unsupported.",
            ),
            source_commit=source_commit,
        )

    if validation_report is None:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.VALIDATION_REPORT_MISSING,
                detail="The selected v1.1 release has no production validation report.",
            ),
            source_commit=source_commit,
        )
    try:
        report = ProductionValidationReportV1_1.model_validate(validation_report)
    except ValidationError:
        return _blocked(
            selected,
            KnowledgeReleaseQualificationBlocker(
                code=KnowledgeReleaseQualificationBlockerCode.VALIDATION_REPORT_INVALID,
                detail="The selected v1.1 production validation report is invalid.",
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
        )

    try:
        verified = artifact_store.load_active_runtime(
            selected.package_id,
            str(selected.artifact_version),
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
