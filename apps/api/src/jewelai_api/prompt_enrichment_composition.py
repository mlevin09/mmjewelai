"""Fail-closed composition of the controlled Prompt Enrichment runtime."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from jewelai_domain import (
    KnowledgeReleaseQualificationStatus,
    ProductionValidationReport,
    qualify_knowledge_release,
)
from jewelai_domain.knowledge_activation_v1_1 import ProductionValidationReportV1_1
from jewelai_domain.knowledge_qualification_v1_1 import qualify_knowledge_release_v1_1
from jewelai_domain.knowledge_runtime import (
    knowledge_contract_version,
    knowledge_store,
    validate_active_knowledge,
)
from jewelai_persistence.repository import PersistenceRepository
from pydantic import ValidationError

from .artifacts import RuntimeArtifacts
from .prompt_enrichment_runtime import PromptEnrichmentRuntimeService
from .settings import PromptEnrichmentRuntimeConfig

PROMPT_ENRICHMENT_RUNTIME_COMPOSITION_VERSION = "1.0.0"


class PromptEnrichmentCompositionErrorCode(StrEnum):
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    EVIDENCE_INVALID = "evidence_invalid"
    RELEASE_NOT_QUALIFIED = "release_not_qualified"


class PromptEnrichmentCompositionError(RuntimeError):
    """Bounded startup failure that never includes evidence payloads or filesystem paths."""

    def __init__(self, code: PromptEnrichmentCompositionErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


def _load_evidence(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PromptEnrichmentCompositionError(
            PromptEnrichmentCompositionErrorCode.EVIDENCE_UNAVAILABLE,
            "Configured Prompt Enrichment release evidence is unavailable",
        ) from exc
    except json.JSONDecodeError as exc:
        raise PromptEnrichmentCompositionError(
            PromptEnrichmentCompositionErrorCode.EVIDENCE_INVALID,
            "Configured Prompt Enrichment release evidence is invalid",
        ) from exc


def compose_prompt_enrichment_runtime(
    config: PromptEnrichmentRuntimeConfig,
    repository: PersistenceRepository,
    artifacts: RuntimeArtifacts,
    *,
    clock: Callable[[], datetime] | None = None,
    uuid_factory: Callable[[], UUID] | None = None,
) -> PromptEnrichmentRuntimeService:
    """Verify one exact configured release before constructing the existing runtime service."""

    active_payload = _load_evidence(config.active_release_path)
    report_payload = _load_evidence(config.validation_report_path)
    store = knowledge_store(config.knowledge_contract_version, config.artifact_root)
    qualify = (
        qualify_knowledge_release_v1_1
        if config.knowledge_contract_version == "1.1.0"
        else qualify_knowledge_release
    )
    qualification = qualify(
        store,
        config.candidate,
        active_release=active_payload,
        validation_report=report_payload,
    )
    if qualification.status != KnowledgeReleaseQualificationStatus.QUALIFIED:
        blocker = qualification.blockers[0].code.value if qualification.blockers else "unknown"
        raise PromptEnrichmentCompositionError(
            PromptEnrichmentCompositionErrorCode.RELEASE_NOT_QUALIFIED,
            f"Configured Prompt Enrichment release is not qualified ({blocker})",
        )
    if qualification.qualification_contract_version != config.qualification_contract_version:
        raise PromptEnrichmentCompositionError(
            PromptEnrichmentCompositionErrorCode.RELEASE_NOT_QUALIFIED,
            "Configured Prompt Enrichment qualification contract does not match",
        )
    try:
        if (
            knowledge_contract_version(active_payload) != config.knowledge_contract_version
            or knowledge_contract_version(report_payload) != config.knowledge_contract_version
        ):
            raise ValueError("Configured Knowledge evidence version mismatch")
        active = validate_active_knowledge(active_payload)
        report_model = (
            ProductionValidationReportV1_1
            if config.knowledge_contract_version == "1.1.0"
            else ProductionValidationReport
        )
        report = report_model.model_validate(report_payload)
    except (ValidationError, ValueError) as exc:
        raise PromptEnrichmentCompositionError(
            PromptEnrichmentCompositionErrorCode.EVIDENCE_INVALID,
            "Configured Prompt Enrichment release evidence is invalid",
        ) from exc

    return PromptEnrichmentRuntimeService(
        repository,
        artifacts,
        store,
        knowledge_package_id=config.candidate.package_id,
        knowledge_artifact_version=str(config.candidate.artifact_version),
        active_release=active,
        validation_report=report,
        clock=clock or (lambda: datetime.now(UTC)),
        uuid_factory=uuid_factory or uuid4,
    )
