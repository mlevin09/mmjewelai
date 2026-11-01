"""Explicit F05 read-only negotiation; no admission or implicit profile upgrade."""

from typing import Literal

from jewelai_domain.clarification_state import (
    EffectiveUnresolvedFrontier,
    EvidenceScope,
    StrictEvidenceModel,
    evidence_bytes,
)
from jewelai_domain.compatibility import CompatibilityReadinessProjection
from jewelai_domain.continuation import ContinuationFrame
from jewelai_domain.preservation import PreservationConflict, ProtectionProjection
from jewelai_prompts.downstream_preparation import GenerationPreparationError, PreparationErrorCode
from jewelai_prompts.final_prompt import FinalPromptReadiness
from jewelai_prompts.final_prompt_v4 import (
    FinalPromptSnapshotV3,
    UserReadableJewelryDescriptionV3,
    assemble_internal_final_prompt_v4,
)

from .clarification import ClarificationQuestion
from .clarification_v2 import ClarificationQuestionV2
from .compatibility_projection import project_legacy_readiness
from .continuation_history import read_native_frame


class ContinuationReadError(ValueError):
    def __init__(self, status, code, detail):
        super().__init__(detail)
        self.status, self.code = status, code


class NativePreviewQuestion(StrictEvidenceModel):
    question_kind: Literal["NATIVE"]
    retained_base: Literal["L", "F"]
    native_question: ClarificationQuestionV2 | ClarificationQuestion


class ContinuationStateV3(StrictEvidenceModel):
    schema_version: Literal["3.0.0"]
    scope: EvidenceScope
    retained_base: Literal["L", "F"]
    extension_profile: Literal["jewelai.prompt-enrichment.f05/1.0.0"] | None
    continuation_enabled: bool
    current_frame: ContinuationFrame
    questions: tuple[NativePreviewQuestion, ...]
    protection_projection: ProtectionProjection
    native_frontier: EffectiveUnresolvedFrontier | None
    compatibility_projection: CompatibilityReadinessProjection | None
    status: Literal[
        "enrichment_completed",
        "clarification_available",
        "blocking_clarification_unresolved",
        "clarification_answer_recorded",
        "correction_applied",
        "correction_deferred",
        "final_output_ready",
        "final_output_ready_with_unresolved",
        "final_output_blocked",
        "awaiting_keep_release",
    ]
    description: UserReadableJewelryDescriptionV3
    preparation_expectations: None


def read_preview(service, sid, oid, *, final=False, if_match=None, projection=None):
    """Validate sources and build current output within the same scoped transaction."""
    with service.repository.read_enrichment_history(sid, oid) as repo:
        try:
            native = read_native_frame(service, repo, sid, oid)
            base = "F" if native.session.question_artifact_version == "2.0.0" else "L"
            if final:
                if if_match is None:
                    raise ContinuationReadError(
                        422, "missing_if_match", "Current frame If-Match is required"
                    )
                # Accept the exact strong ETag syntax as well as its bare SHA value.
                expected = native.frame.history_root_sha256
                if if_match not in (expected, '"' + expected + '"'):
                    raise ContinuationReadError(
                        409, "stale_clarification_plan", "Current workflow frame changed"
                    )
                if projection != ("jewelai.legacy-l.compat/1.0.0" if base == "L" else None):
                    raise ContinuationReadError(
                        422,
                        "invalid_projection",
                        "Projection does not match retained native profile",
                    )
            compat = (
                project_legacy_readiness(service, repo, native, sid, oid) if base == "L" else None
            )
            original = native.snapshot
            snapshot = FinalPromptSnapshotV3(
                **original.model_dump(
                    exclude={
                        "schema_version",
                        "contract_profile",
                        "effective_unresolved_frontier",
                        "cause_definitions",
                    }
                ),
                schema_version="3.0.0",
                retained_base=base,
                extension_profile=None,
                current_frame=native.frame,
                protection_projection=native.protection,
                compatibility_projection=compat,
                native_frontier=getattr(original, "effective_unresolved_frontier", None),
                cause_definitions=getattr(original, "cause_definitions", ()),
            )
            bound = service._for_session(sid, oid, repository=repo)
            output = assemble_internal_final_prompt_v4(
                snapshot, dictionary=bound.artifacts.dictionary, templates=bound.artifacts.prompts
            )
            if len(evidence_bytes(output)) > 1_048_576:
                raise ContinuationReadError(
                    422, "artifact_capacity_exceeded", "Current output exceeds artifact capacity"
                )
            if final:
                if output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED:
                    raise ContinuationReadError(
                        409, "final_output_blocked", "Provider-neutral final output is not ready"
                    )
                return output
            readiness = output.internal_final_prompt.readiness
            state = ContinuationStateV3(
                schema_version="3.0.0",
                scope=native.protection.scope,
                retained_base=base,
                extension_profile=None,
                continuation_enabled=False,
                current_frame=native.frame,
                questions=tuple(
                    NativePreviewQuestion(
                        question_kind="NATIVE", retained_base=base, native_question=q
                    )
                    for q in native.plan.questions
                ),
                protection_projection=native.protection,
                native_frontier=snapshot.native_frontier,
                compatibility_projection=compat,
                status="final_output_blocked"
                if readiness == FinalPromptReadiness.BLOCKED
                else "final_output_ready_with_unresolved"
                if readiness == FinalPromptReadiness.READY_WITH_UNRESOLVED
                else "final_output_ready",
                description=output.description,
                preparation_expectations=None,
            )
            if len(evidence_bytes(state)) > 1_048_576:
                raise ContinuationReadError(
                    422, "artifact_capacity_exceeded", "Current state exceeds artifact capacity"
                )
            return state
        except ContinuationReadError:
            raise
        except PreservationConflict:
            raise ContinuationReadError(
                409,
                "protected_state_inconsistent",
                "Current canonical state conflicts with active preservation",
            ) from None
        except GenerationPreparationError as exc:
            if exc.code == PreparationErrorCode.CAPACITY:
                raise ContinuationReadError(
                    422, "artifact_capacity_exceeded", "Current output exceeds artifact capacity"
                ) from None
            raise ContinuationReadError(
                500, "invalid_durable_history", "Scoped enrichment history failed validation"
            ) from None
        except ValueError:
            raise ContinuationReadError(
                500, "invalid_durable_history", "Scoped enrichment history failed validation"
            ) from None
