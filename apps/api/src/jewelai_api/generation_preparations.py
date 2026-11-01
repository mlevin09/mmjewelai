"""Authoritative preparation only: no generation, outbox, publisher or provider call."""

from jewelai_domain.knowledge_storage import KnowledgeArtifactStorageError
from jewelai_persistence import KnowledgeReleasePinConflictError
from jewelai_persistence.preparations import (
    PreparationConflictError,
    PreparationIntegrityError,
    commit_preparation,
    read_preparation,
)
from jewelai_prompts import FinalPromptInputError, build_generation_preparation
from jewelai_prompts.downstream_preparation import preparation_hash
from pydantic import ValidationError

from .preparation_contracts import (
    GenerationPreparationRequest,
    GenerationPreparationRequestV2,
    GenerationPreparationSummary,
    GenerationPreparationSummaryV2,
)


def preparation_expectations(source, gate):
    f04 = source.schema_version == "3.0.0"
    return (GenerationPreparationRequestV2 if f04 else GenerationPreparationRequest)(
        schema_version="2.0.0" if f04 else "1.0.0",
        **(
            {"expected_effective_frontier_hash": gate.effective_unresolved_frontier_hash}
            if f04
            else {}
        ),
        expected_revision_id=gate.revision.revision_id,
        expected_enrichment_cycle_id=gate.enrichment_cycle_id,
        expected_enrichment_cycle_number=gate.enrichment_cycle_number,
        expected_enrichment_result_hash=gate.enrichment_result_hash,
        expected_handoff_hash=source.content_hash,
        expected_clarification_plan_hash=gate.clarification_plan_hash,
        expected_decision_frontier_hash=gate.decision_frontier_hash,
    )


class GenerationPreparationService:
    def __init__(self, repository, runtime):
        self.repository = repository
        self.runtime = runtime

    def create(self, session_id, organization_id, principal_id, idempotency_key, request):
        request = (
            GenerationPreparationRequestV2.model_validate(request)
            if getattr(request, "schema_version", None) == "2.0.0"
            or isinstance(request, dict)
            and request.get("schema_version") == "2.0.0"
            else GenerationPreparationRequest.model_validate(request)
        )

        def build(reader):
            from .prompt_enrichment_runtime import (
                PromptEnrichmentRuntimeError,
                PromptEnrichmentRuntimeErrorCode,
            )

            try:
                source, gate = self.runtime.build_preparation_source(
                    reader, session_id, organization_id
                )
            except (KnowledgeArtifactStorageError, KnowledgeReleasePinConflictError):
                raise PromptEnrichmentRuntimeError(
                    PromptEnrichmentRuntimeErrorCode.INVALID_KNOWLEDGE_RELEASE,
                    "The selected ACTIVE Knowledge release failed verification",
                ) from None
            except (FinalPromptInputError, ValidationError):
                raise PreparationIntegrityError("Authoritative source failed validation") from None
            current = preparation_expectations(source, gate)
            if request.schema_version != current.schema_version:
                raise PreparationConflictError("artifact_mismatch")
            if (
                request.schema_version == "2.0.0"
                and request.expected_effective_frontier_hash
                != current.expected_effective_frontier_hash
            ):
                raise PreparationConflictError("stale_clarification_plan")
            for fields, code in (
                (("expected_revision_id",), "stale_revision"),
                (
                    (
                        "expected_enrichment_cycle_id",
                        "expected_enrichment_cycle_number",
                        "expected_enrichment_result_hash",
                    ),
                    "enrichment_cycle_mismatch",
                ),
                (
                    ("expected_clarification_plan_hash", "expected_decision_frontier_hash"),
                    "stale_clarification_plan",
                ),
                (("expected_handoff_hash",), "preparation_stale"),
            ):
                if any(getattr(request, field) != getattr(current, field) for field in fields):
                    raise PreparationConflictError(code)
            return build_generation_preparation(
                source, gate, preparation_id=self.runtime._uuid(), created_at=self.runtime._clock()
            )

        summary, replayed = commit_preparation(
            self.repository,
            organization_id=organization_id,
            session_id=session_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            request_hash=preparation_hash(
                f"jewelai.preparation.command/{request.schema_version}", request
            ),
            builder=build,
        )
        return _summary(summary), replayed

    def get(self, session_id, organization_id, principal_id, preparation_id):
        return _summary(
            read_preparation(
                self.repository,
                organization_id=organization_id,
                session_id=session_id,
                principal_id=principal_id,
                preparation_id=preparation_id,
            )
        )


def _summary(value):
    return (
        GenerationPreparationSummaryV2
        if value.get("schema_version") == "2.0.0"
        else GenerationPreparationSummary
    ).model_validate(value)
