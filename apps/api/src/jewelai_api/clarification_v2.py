"""Approved F04 versioned clarification evidence, using the existing planning engine.

These are new-profile contracts. They never reinterpret a retained Plan1/answer1.
Canonical mutation and durable causal proof stay at the revision/repository boundary.
"""

from typing import Annotated, Literal
from uuid import UUID

from jewelai_domain.clarification_state import (
    ArtifactPins,
    CauseDefinition,
    CauseState,
    EffectiveUnresolvedFrontier,
    EvidenceScope,
    FrontierCore,
    OccurrenceRef,
    OriginalQuestionReference,
    PlanReference,
    Sha256,
    StrictEvidenceModel,
    TargetRef,
    evidence_hash,
)
from jewelai_domain.questions_v2 import QuestionIdV2
from jewelai_domain.rules_v2 import RuleDecisionV2
from pydantic import Field, model_validator

from .clarification import (
    ClarificationPlan,
    ClarificationQuestion,
    UnaskedClarificationEvidence,
)
from .clarification_answers import (
    ClarificationAnswerResult,
    ClarificationDecision,
)
from .conflict_evidence import ConflictEvidence, stable_id


class InitialTrigger(StrictEvidenceModel):
    kind: Literal["initial"]
    message_id: UUID


class AcceptedResultTrigger(StrictEvidenceModel):
    kind: Literal["answer", "correction"]
    record_id: UUID
    content_hash: Sha256
    previous_plan_id: UUID
    previous_plan_hash: Sha256
    message_id: UUID
    message_content_sha256: Sha256


class ResumeTrigger(StrictEvidenceModel):
    kind: Literal["explicit_resume"]
    request_id: UUID
    request_hash: Sha256
    message_id: UUID
    cause_id: str
    previous_plan_id: UUID
    previous_plan_hash: Sha256


PlanTrigger = Annotated[
    InitialTrigger | AcceptedResultTrigger | ResumeTrigger,
    Field(discriminator="kind"),
]


class RelevantChangeReference(StrictEvidenceModel):
    accepted_result_record_id: UUID
    accepted_result_hash: Sha256
    old_context_fingerprint: Sha256
    new_context_fingerprint: Sha256


class ClarificationOptionV2(StrictEvidenceModel):
    option_id: str = Field(pattern=r"^option_[0-9a-f]{64}$")
    value: str
    label: str
    source_occurrence_refs: tuple[OccurrenceRef, ...]


class ClarificationQuestionV2(ClarificationQuestion, StrictEvidenceModel):
    semantic_question_id: QuestionIdV2
    target: TargetRef
    options: tuple[ClarificationOptionV2, ...]
    cause_id: str
    conflict_id: str | None
    offer_ordinal: int = Field(strict=True, ge=0)
    offer_trigger: Literal["initial", "explicit_resume", "relevant_change"]
    trigger_ref: PlanTrigger | RelevantChangeReference
    allowed_decisions: tuple[ClarificationDecision, ...]
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    source_plan_id: UUID

    @model_validator(mode="after")
    def validate_material_shape(self):
        if self.semantic_question_id == QuestionIdV2.METAL_MATERIAL and (
            self.target
            != TargetRef(
                concrete_target="metal.material",
                owner_kind="product_body",
                owner_id=None,
                group_id=None,
            )
            or self.allowed_decisions
            != (
                ClarificationDecision.SELECT_OPTION,
                ClarificationDecision.SKIP,
                ClarificationDecision.UNKNOWN,
            )
            or len(self.options) < 2
            or self.conflict_id is None
            or any(not item.source_occurrence_refs for item in self.options)
        ):
            raise ValueError("Material offer lacks approved scoped choices")
        values = tuple(item.value for item in self.options)
        if values != tuple(sorted(set(values))):
            raise ValueError("Options require unique deterministic Dictionary-ID order")
        return self


class ClarificationPlanV2(ClarificationPlan, StrictEvidenceModel):
    plan_version: Literal["2.0.0"]
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    scope: EvidenceScope
    plan_id: UUID
    enrichment_cycle_id: UUID
    enrichment_cycle_number: int = Field(strict=True, ge=1)
    enrichment_result_hash: Sha256
    revision_sha256: Sha256
    artifact_pins: ArtifactPins
    rule_decision: RuleDecisionV2
    questions: tuple[ClarificationQuestionV2, ...]
    unasked_evidence: tuple[UnaskedClarificationEvidence, ...]
    conflicts: tuple[ConflictEvidence, ...]
    cause_definitions: tuple[CauseDefinition, ...]
    frontier_core: FrontierCore
    trigger: PlanTrigger

    @model_validator(mode="after")
    def validate_f04_plan(self):
        core = self.frontier_core
        definitions = {c.cause_id: c for c in self.cause_definitions}
        states = {s.cause_id: s for s in core.cause_states}
        if (
            core.scope != self.scope
            or str(core.current_revision_id) != self.design_revision_id
            or core.revision_sha256 != self.revision_sha256
            or set(definitions) != set(states)
            or tuple(definitions) != tuple(sorted(definitions))
            or any(d.scope != self.scope for d in definitions.values())
            or (self.question_artifact_version, self.rules_artifact_version) != ("2.0.0", "2.0.0")
        ):
            raise ValueError("F plan scope/current-frontier mismatch")
        conflicts = {c.conflict_id: c for c in self.conflicts}
        if len(conflicts) != len(self.conflicts) or any(
            c.context.scope != self.scope or c.context.artifact_pins != self.artifact_pins
            for c in conflicts.values()
        ):
            raise ValueError("Plan conflict scope/artifact mismatch")
        for cause in definitions.values():
            if cause.kind.startswith("material_"):
                conflict = conflicts.get(cause.source_conflict_id)
                if (
                    conflict is None
                    or conflict.target != cause.target
                    or cause.release_pin != conflict.context.release_pin
                    or cause.kind != "material_" + conflict.kind
                ):
                    raise ValueError("Material cause has no exact scoped source conflict")
        for question in self.questions:
            cause = definitions.get(question.cause_id)
            state = states.get(question.cause_id)
            if (
                cause is None
                or state is None
                or state.status != "OPEN"
                or state.offer_state != "AVAILABLE"
                or cause.target != question.target
                or question.source_plan_id != self.plan_id
                or question.design_revision_id != self.design_revision_id
            ):
                raise ValueError("Question does not belong to a current available cause")
        expected = not any(s.blocks_current for s in core.cause_states)
        # Rules may independently block canonical readiness. Question presentation does
        # not decide whether an unanswered historical cause is currently blocking.
        if self.rule_decision.decision == "block":
            expected = False
        if self.can_continue_without_answers != expected:
            raise ValueError("F plan progression disagrees with effective current causes")
        return self

    @model_validator(mode="after")
    def validate_hash_and_progression(self):
        # Override the frozen L validator: F has separate presentation/progression axes.
        if self.content_hash != evidence_hash(
            self.model_dump(mode="json", exclude={"content_hash"})
        ):
            raise ValueError("F clarification plan checksum mismatch")
        ids = tuple(e.evidence_id for e in self.constraint_evidence)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("Constraint evidence order mismatch")
        return self


class AcceptedTargetEvidence(StrictEvidenceModel):
    target: TargetRef
    source_message_id: UUID
    source_candidate_ids: tuple[str, ...]
    normalization_refs: tuple[str, ...]
    before_revision_id: UUID
    before_state_sha256: Sha256
    after_revision_id: UUID
    after_state_sha256: Sha256
    accepted_dictionary_value: str | None
    transition: Literal["APPLIED", "NO_CHANGE"]


class ResolutionAssertion(StrictEvidenceModel):
    cause_id: str
    target: TargetRef
    source_message_id: UUID
    accepted_target_evidence_index: int | None = Field(ge=0, strict=True)
    method: Literal[
        "selected_offered_value",
        "accepted_correction",
        "same_value_explicit_resolution",
        "offer_rejected",
    ]
    disposition: Literal["resolved", "superseded", "rejected"]
    reason_code: str
    resulting_revision_id: UUID
    post_state_sha256: Sha256

    @model_validator(mode="after")
    def validate_index(self):
        if (self.method == "offer_rejected") != (self.accepted_target_evidence_index is None):
            raise ValueError("Resolution requires exact accepted target or valid offer rejection")
        return self


class ClarificationAnswerResultV2(ClarificationAnswerResult, StrictEvidenceModel):
    answer_version: Literal["2.0.0"]
    contract_profile: Literal["jewelai.prompt-enrichment.f04/2.0.0"]
    scope: EvidenceScope
    source_plan_id: UUID
    selected_option_id: str | None
    selected_option: ClarificationOptionV2 | None
    semantic_question_id: QuestionIdV2
    target: TargetRef
    accepted_target_evidence: tuple[AcceptedTargetEvidence, ...]
    resolution_assertions: tuple[ResolutionAssertion, ...]

    @model_validator(mode="after")
    def validate_causal_shape(self):
        if self.session_id != self.scope.session_id:
            raise ValueError("Answer scope mismatch")
        for assertion in self.resolution_assertions:
            index = assertion.accepted_target_evidence_index
            if index is not None and (
                index >= len(self.accepted_target_evidence)
                or self.accepted_target_evidence[index].target != assertion.target
                or self.accepted_target_evidence[index].source_message_id
                != assertion.source_message_id
            ):
                raise ValueError("Resolution accepted-target index mismatch")
        return self


class ClarificationAnswerRequestV2(StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    clarification_plan_id: UUID
    plan_content_hash: Sha256
    clarification_id: str
    decision: ClarificationDecision
    selected_option: str | None
    selected_option_id: str | None
    expected_revision_id: UUID
    answer_id: UUID
    message_id: UUID

    @model_validator(mode="after")
    def validate_selection_pair(self):
        select = self.decision == ClarificationDecision.SELECT_OPTION
        if select != (self.selected_option is not None and self.selected_option_id is not None):
            raise ValueError("SELECT_OPTION requires the exact offered ID and value")
        if not select and (self.selected_option is not None or self.selected_option_id is not None):
            raise ValueError("Only SELECT_OPTION accepts a selection pair")
        return self


class InitialRequestV2(StrictEvidenceModel):
    schema_version: Literal["2.0.0"]
    expected_revision_id: UUID
    message_id: UUID


class CorrectionRequestV2(InitialRequestV2):
    expected_enrichment_cycle_id: UUID
    expected_enrichment_result_hash: Sha256
    expected_clarification_plan_hash: Sha256


class ResumeRequest(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    request_id: UUID
    message_id: UUID
    expected_revision_id: UUID
    expected_enrichment_cycle_id: UUID
    expected_enrichment_result_hash: Sha256
    expected_clarification_plan_hash: Sha256


class ResumeResult(StrictEvidenceModel):
    schema_version: Literal["1.0.0"]
    request_id: UUID
    cause_id: str
    emitted_plan_id: UUID
    emitted_plan_hash: Sha256
    emitted_question_id: str
    enrichment_cycle_id: UUID
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_hash(self):
        if self.content_hash != evidence_hash(
            self.model_dump(mode="json", exclude={"content_hash"})
        ):
            raise ValueError("Resume result integrity mismatch")
        return self


def frontier_core(scope, revision, states):
    payload = dict(
        schema_version="1.0.0",
        scope=scope,
        current_revision_id=revision.revision_id,
        revision_sha256=evidence_hash(revision),
        profile="jewelai.prompt-enrichment.f04/2.0.0",
        cause_states=tuple(sorted(states, key=lambda s: s.cause_id)),
    )
    return FrontierCore(**payload, content_hash=evidence_hash(payload))


def open_cause_state(definition, *, criticality, offer_state):
    return CauseState(
        cause_id=definition.cause_id,
        status="OPEN",
        criticality=criticality,
        offer_state=offer_state,
        last_answer_ref=None,
        resolution_ref=None,
        superseded_by_cause_id=None,
        rule_ref=definition.rule_ref,
        availability_target_ref=definition.target,
    )


def cause_definition(**payload):
    identity = {"schema_version": "1.0.0", **payload}
    identity["cause_id"] = stable_id("cause_", "jewelai.f04.cause/1.0.0", identity)
    return CauseDefinition(**identity, content_hash=evidence_hash(identity))


def decode_clarification_plan(value):
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if isinstance(payload, dict) and payload.get("plan_version") == "2.0.0":
        return ClarificationPlanV2.model_validate(payload)
    return ClarificationPlan.model_validate(payload)


def decode_answer_result(value):
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if isinstance(payload, dict) and payload.get("answer_version") == "2.0.0":
        return ClarificationAnswerResultV2.model_validate(payload)
    return ClarificationAnswerResult.model_validate(payload)


def seal_frontier(plan, plans):
    """Seal an already validated core using actual retained plan/question identities."""
    by_id = {p.plan_id: p for p in plans}
    by_id[plan.plan_id] = plan
    origins = sorted({c.origin_plan_id for c in plan.cause_definitions}, key=str)
    if any(origin not in by_id for origin in origins):
        raise ValueError("Missing scoped origin plan")
    questions = {}
    for prior in sorted(by_id.values(), key=lambda p: p.enrichment_cycle_number):
        for question in prior.questions:
            questions.setdefault(
                question.cause_id,
                OriginalQuestionReference(
                    cause_id=question.cause_id,
                    plan_id=prior.plan_id,
                    question_id=question.clarification_id,
                ),
            )
    payload = dict(
        schema_version="1.0.0",
        frontier_core=plan.frontier_core,
        current_plan_ref=PlanReference(plan_id=plan.plan_id, content_hash=plan.content_hash),
        origin_plan_refs=tuple(
            PlanReference(plan_id=i, content_hash=by_id[i].content_hash) for i in origins
        ),
        origin_question_refs=tuple(questions[k] for k in sorted(questions)),
    )
    return EffectiveUnresolvedFrontier(**payload, content_hash=evidence_hash(payload))
