"""Internal durable bridge for validated clarification and correction results.

Processing remains outside the database transaction. These entry points validate immutable API
contracts before persistence; the repository then rechecks authoritative session state under a
database lock and commits every related record atomically. No public route is wired in this step.
"""

from datetime import datetime
from uuid import UUID

from jewelai_persistence import (
    ClarificationAnswerRecord,
    PersistenceRepository,
    UserCorrectionRecord,
)
from jewelai_prompts import PromptEnrichmentResult

from .clarification_answers import ClarificationAnswerResult
from .correction_enrichment import CorrectionReenrichmentResult


def commit_clarification_answer_result(
    repository: PersistenceRepository,
    *,
    answer_record_id: UUID,
    organization_id: UUID,
    expected_revision_id: UUID,
    result: ClarificationAnswerResult,
    created_at: datetime,
    next_enrichment_cycle_id: UUID | None = None,
    next_enrichment_result: PromptEnrichmentResult | None = None,
) -> ClarificationAnswerResult:
    """Validate and atomically persist one authoritative clarification result."""

    validated = ClarificationAnswerResult.model_validate(result)
    record = repository.commit_clarification_answer(
        answer_record_id=answer_record_id,
        session_id=validated.session_id,
        organization_id=organization_id,
        expected_revision_id=expected_revision_id,
        result_payload=validated.model_dump(mode="json"),
        created_at=created_at,
        next_enrichment_cycle_id=next_enrichment_cycle_id,
        next_enrichment_result=next_enrichment_result,
    )
    return _answer_result(record)


def get_clarification_answer_result(
    repository: PersistenceRepository,
    *,
    session_id: UUID,
    plan_content_hash: str,
    clarification_id: str,
    organization_id: UUID,
) -> ClarificationAnswerResult:
    record = repository.get_clarification_answer(
        session_id,
        plan_content_hash,
        clarification_id,
        organization_id,
    )
    return _answer_result(record)


def list_clarification_answer_results(
    repository: PersistenceRepository,
    *,
    session_id: UUID,
    organization_id: UUID,
) -> tuple[ClarificationAnswerResult, ...]:
    return tuple(
        _answer_result(record)
        for record in repository.list_clarification_answers(session_id, organization_id)
    )


def commit_user_correction_result(
    repository: PersistenceRepository,
    *,
    correction_record_id: UUID,
    next_enrichment_cycle_id: UUID,
    organization_id: UUID,
    expected_revision_id: UUID,
    result: CorrectionReenrichmentResult,
    created_at: datetime,
) -> CorrectionReenrichmentResult:
    """Validate and atomically persist one correction and its prepared next cycle."""

    validated = CorrectionReenrichmentResult.model_validate(result)
    record = repository.commit_user_correction(
        correction_record_id=correction_record_id,
        next_enrichment_cycle_id=next_enrichment_cycle_id,
        session_id=validated.session_id,
        organization_id=organization_id,
        expected_revision_id=expected_revision_id,
        result_payload=validated.model_dump(mode="json"),
        created_at=created_at,
    )
    return _correction_result(record)


def get_user_correction_result(
    repository: PersistenceRepository,
    *,
    session_id: UUID,
    correction_record_id: UUID,
    organization_id: UUID,
) -> CorrectionReenrichmentResult:
    record = repository.get_user_correction(
        session_id,
        correction_record_id,
        organization_id,
    )
    return _correction_result(record)


def list_user_correction_results(
    repository: PersistenceRepository,
    *,
    session_id: UUID,
    organization_id: UUID,
) -> tuple[CorrectionReenrichmentResult, ...]:
    return tuple(
        _correction_result(record)
        for record in repository.list_user_corrections(session_id, organization_id)
    )


def _answer_result(record: ClarificationAnswerRecord) -> ClarificationAnswerResult:
    return ClarificationAnswerResult.model_validate(record.result_payload)


def _correction_result(record: UserCorrectionRecord) -> CorrectionReenrichmentResult:
    return CorrectionReenrichmentResult.model_validate(record.result_payload)
