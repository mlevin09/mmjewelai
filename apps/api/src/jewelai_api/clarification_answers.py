"""Explicit answer processing for immutable clarification plans.

This module is an internal primitive only. It validates one answer, uses Parser Proposal and the
domain revision transition for supported changes, and performs no persistence or re-enrichment.
"""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from jewelai_domain.dictionary import DictionaryCategory, DictionaryRegistry, EntryLifecycle
from jewelai_domain.knowledge_activation import ActiveKnowledgeRuntime
from jewelai_domain.models import ImmutableModel, MessageSource
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_domain.questions import DictionaryAnswerContract, QuestionCatalog, QuestionId
from jewelai_domain.revisions import RevisionConflict, revise_design
from jewelai_domain.rules import AskDecision, RuleRegistry
from jewelai_parser import (
    CandidateUpdate,
    ParserCandidate,
    ParserTarget,
    build_parser_proposal,
)
from jewelai_parser.models import TermCandidate
from pydantic import Field, model_validator

from .clarification import (
    ClarificationCategory,
    ClarificationEvidence,
    ClarificationImportance,
    ClarificationOption,
    ClarificationPlan,
)

CLARIFICATION_ANSWER_VERSION = "1.0.0"


class ClarificationDecision(StrEnum):
    SELECT_OPTION = "SELECT_OPTION"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    SKIP = "SKIP"
    UNKNOWN = "UNKNOWN"


class ClarificationAnswerOutcome(StrEnum):
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"
    DEFERRED = "DEFERRED"


class ClarificationAnswerReason(StrEnum):
    USER_SELECTED_OFFERED_OPTION = "user_selected_offered_option"
    USER_ACCEPTED_PREFERENCE = "user_accepted_preference"
    USER_ACCEPTED_RECOMMENDATION = "user_accepted_recommendation"
    USER_REJECTED_OFFER = "user_rejected_offer"
    USER_SKIPPED = "user_skipped"
    USER_DOES_NOT_KNOW = "user_does_not_know"
    VALUE_ALREADY_CURRENT = "value_already_current"
    TARGET_PROTECTED = "target_protected"
    UNSUPPORTED_APPLICATION = "unsupported_application"
    PARSER_REJECTED = "parser_rejected"


class ClarificationAnswerErrorCode(StrEnum):
    INVALID_PLAN = "invalid_plan"
    CROSS_SESSION = "cross_session"
    PLAN_MISMATCH = "plan_mismatch"
    UNKNOWN_QUESTION = "unknown_question"
    STALE_REVISION = "stale_revision"
    RELEASE_MISMATCH = "release_mismatch"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    QUESTION_MISMATCH = "question_mismatch"
    INVALID_DECISION = "invalid_decision"
    INVALID_OPTION = "invalid_option"
    QUESTION_NO_LONGER_APPLICABLE = "question_no_longer_applicable"
    CONFLICTING_ANSWER = "conflicting_answer"


class ClarificationAnswerError(ValueError):
    """Typed fail-closed validation error for the internal answer boundary."""

    def __init__(self, code: ClarificationAnswerErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class ClarificationAnswer(ImmutableModel):
    session_id: UUID
    plan_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    clarification_id: str
    decision: ClarificationDecision
    selected_option: str | None = None
    expected_revision_id: UUID
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_validation_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: MessageSource

    @model_validator(mode="after")
    def validate_decision_shape(self):
        if self.decision == ClarificationDecision.SELECT_OPTION:
            if self.selected_option is None:
                raise ValueError("SELECT_OPTION requires selected_option")
        elif self.selected_option is not None:
            raise ValueError("only SELECT_OPTION may provide selected_option")
        return self


class ClarificationAnswerResult(ImmutableModel):
    answer_version: Literal["1.0.0"] = CLARIFICATION_ANSWER_VERSION
    session_id: UUID
    plan_content_hash: str
    clarification_id: str
    semantic_question_id: QuestionId
    decision: ClarificationDecision
    selected_option: ClarificationOption | None = None
    source_candidate_ids: tuple[str, ...]
    source_proposal_ids: tuple[str, ...]
    evidence: tuple[ClarificationEvidence, ...]
    target: str
    subject: str | None = None
    previous_revision_id: UUID
    new_revision_id: UUID | None = None
    resulting_revision: AnyDesignRevision | None = None
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: str
    knowledge_validation_report_sha256: str
    question_artifact_version: str
    rules_artifact_version: str
    outcome: ClarificationAnswerOutcome
    reason: ClarificationAnswerReason
    question_resolved: bool
    blocks_progression: bool
    answer_hash: str
    content_hash: str

    @model_validator(mode="after")
    def validate_result(self):
        if (self.new_revision_id is None) != (self.resulting_revision is None):
            raise ValueError("new revision identity and snapshot must be present together")
        if self.resulting_revision is not None:
            if (
                self.resulting_revision.revision_id != self.new_revision_id
                or self.resulting_revision.parent_revision_id != self.previous_revision_id
            ):
                raise ValueError("answer result revision lineage mismatch")
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if self.content_hash != _hash(payload):
            raise ValueError("clarification answer result content hash mismatch")
        return self


_PARSER_TARGET = {
    QuestionId.CENTER_STONE_SHAPE: ParserTarget.CENTER_STONE_SHAPE,
    QuestionId.CENTER_STONE_SETTING: ParserTarget.CENTER_STONE_SETTING,
    QuestionId.METAL_COLOR: ParserTarget.METAL_COLOR,
}

_CATEGORY_BY_QUESTION = {
    QuestionId.CENTER_STONE_SHAPE: DictionaryCategory.STONE_SHAPE,
    QuestionId.CENTER_STONE_SETTING: DictionaryCategory.STONE_SETTING,
    QuestionId.METAL_COLOR: DictionaryCategory.METAL_COLOR,
}


def process_clarification_answer(
    plan: ClarificationPlan,
    answer: ClarificationAnswer,
    *,
    authoritative_session_id: UUID,
    current_revision: AnyDesignRevision | object,
    active_release: ActiveKnowledgeRuntime,
    dictionary: DictionaryRegistry,
    questions: QuestionCatalog,
    rules: RuleRegistry,
    created_at: datetime,
    previous_results: tuple[ClarificationAnswerResult, ...] = (),
) -> ClarificationAnswerResult:
    """Validate and process one explicit decision without persistence or re-enrichment."""

    try:
        plan = ClarificationPlan.model_validate(plan)
    except ValueError as exc:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.INVALID_PLAN,
            "clarification plan failed integrity validation",
        ) from exc
    answer = ClarificationAnswer.model_validate(answer)
    current_revision = validate_design_revision(current_revision)
    release = ActiveKnowledgeRuntime.model_validate(active_release)

    if answer.session_id != authoritative_session_id:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.CROSS_SESSION,
            "answer does not belong to the authoritative session",
        )
    if answer.plan_content_hash != plan.content_hash:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.PLAN_MISMATCH,
            "answer references a different clarification plan",
        )
    question = next(
        (item for item in plan.questions if item.clarification_id == answer.clarification_id),
        None,
    )
    if question is None:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.UNKNOWN_QUESTION,
            "clarification question does not belong to the plan",
        )
    if (
        answer.expected_revision_id != current_revision.revision_id
        or plan.design_revision_id != str(current_revision.revision_id)
    ):
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.STALE_REVISION,
            "clarification answer references a stale Product State revision",
        )
    _validate_release(plan, answer, release)
    _validate_artifacts(plan, questions, rules)
    _validate_question_lineage(plan, question)
    _validate_question(question, questions, rules, current_revision, plan.role_id)

    answer_hash = _hash(answer.model_dump(mode="json"))
    duplicate = _find_previous(previous_results, answer, answer_hash)
    if duplicate is not None:
        return duplicate

    option = _resolve_decision(question, answer)
    if answer.decision in {
        ClarificationDecision.REJECT,
        ClarificationDecision.SKIP,
        ClarificationDecision.UNKNOWN,
    }:
        outcome, reason = {
            ClarificationDecision.REJECT: (
                ClarificationAnswerOutcome.REJECTED,
                ClarificationAnswerReason.USER_REJECTED_OFFER,
            ),
            ClarificationDecision.SKIP: (
                ClarificationAnswerOutcome.SKIPPED,
                ClarificationAnswerReason.USER_SKIPPED,
            ),
            ClarificationDecision.UNKNOWN: (
                ClarificationAnswerOutcome.UNKNOWN,
                ClarificationAnswerReason.USER_DOES_NOT_KNOW,
            ),
        }[answer.decision]
        return _result(
            plan,
            question,
            answer,
            answer_hash=answer_hash,
            option=None,
            current_revision=current_revision,
            outcome=outcome,
            reason=reason,
            question_resolved=answer.decision == ClarificationDecision.REJECT,
        )

    protected = _current_state(current_revision, question)
    if protected is not None and bool(getattr(protected, "confirmed", False)):
        return _result(
            plan,
            question,
            answer,
            answer_hash=answer_hash,
            option=option,
            current_revision=current_revision,
            outcome=ClarificationAnswerOutcome.DEFERRED,
            reason=ClarificationAnswerReason.TARGET_PROTECTED,
            question_resolved=False,
        )
    proposal = _parser_proposal(question, option, answer, current_revision, dictionary)
    if proposal is None:
        return _result(
            plan,
            question,
            answer,
            answer_hash=answer_hash,
            option=option,
            current_revision=current_revision,
            outcome=ClarificationAnswerOutcome.DEFERRED,
            reason=ClarificationAnswerReason.UNSUPPORTED_APPLICATION,
            question_resolved=False,
        )
    if proposal.issues:
        return _result(
            plan,
            question,
            answer,
            answer_hash=answer_hash,
            option=option,
            current_revision=current_revision,
            outcome=ClarificationAnswerOutcome.DEFERRED,
            reason=ClarificationAnswerReason.PARSER_REJECTED,
            question_resolved=False,
        )
    if not proposal.has_changes:
        return _result(
            plan,
            question,
            answer,
            answer_hash=answer_hash,
            option=option,
            current_revision=current_revision,
            outcome=ClarificationAnswerOutcome.NO_CHANGE,
            reason=ClarificationAnswerReason.VALUE_ALREADY_CURRENT,
            question_resolved=True,
        )
    try:
        revision = revise_design(
            current_revision,
            proposal.proposed_design,
            expected_revision_id=current_revision.revision_id,
            source=answer.source,
            reason="Applied an explicitly authorized clarification answer",
            created_at=created_at,
        )
    except RevisionConflict:
        return _result(
            plan,
            question,
            answer,
            answer_hash=answer_hash,
            option=option,
            current_revision=current_revision,
            outcome=ClarificationAnswerOutcome.DEFERRED,
            reason=ClarificationAnswerReason.PARSER_REJECTED,
            question_resolved=False,
        )
    return _result(
        plan,
        question,
        answer,
        answer_hash=answer_hash,
        option=option,
        current_revision=current_revision,
        new_revision=revision,
        outcome=ClarificationAnswerOutcome.APPLIED,
        reason=(
            ClarificationAnswerReason.USER_SELECTED_OFFERED_OPTION
            if answer.decision == ClarificationDecision.SELECT_OPTION
            else (
                ClarificationAnswerReason.USER_ACCEPTED_RECOMMENDATION
                if question.category == ClarificationCategory.KNOWLEDGE_RECOMMENDATION
                else ClarificationAnswerReason.USER_ACCEPTED_PREFERENCE
            )
        ),
        question_resolved=True,
    )


def _validate_release(plan, answer, release):
    plan_identity = (
        plan.knowledge_package_id,
        plan.knowledge_artifact_version,
        plan.knowledge_runtime_sha256,
        plan.knowledge_validation_report_sha256,
    )
    answer_identity = (
        answer.knowledge_package_id,
        answer.knowledge_artifact_version,
        answer.knowledge_runtime_sha256,
        answer.knowledge_validation_report_sha256,
    )
    release_identity = (
        release.package_id,
        str(release.artifact_version),
        release.runtime_sha256,
        release.validation_report_sha256,
    )
    if plan_identity != answer_identity or plan_identity != release_identity:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.RELEASE_MISMATCH,
            "clarification answer Knowledge release identity does not match",
        )


def _validate_artifacts(plan, questions, rules):
    if (
        plan.question_artifact_version != questions.artifact_version
        or plan.rules_artifact_version != rules.artifact_version
    ):
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.ARTIFACT_MISMATCH,
            "clarification artifacts no longer match the plan",
        )


def _validate_question_lineage(plan, question):
    if (
        question.design_revision_id != plan.design_revision_id
        or question.knowledge_package_id != plan.knowledge_package_id
        or question.knowledge_artifact_version != plan.knowledge_artifact_version
        or question.knowledge_runtime_sha256 != plan.knowledge_runtime_sha256
        or question.knowledge_validation_report_sha256 != plan.knowledge_validation_report_sha256
        or question.question_artifact_version != plan.question_artifact_version
        or question.rules_artifact_version != plan.rules_artifact_version
    ):
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.QUESTION_MISMATCH,
            "clarification question lineage does not match its plan",
        )


def _validate_question(question, questions, rules, revision, role_id):
    catalog_question = questions.get_question(question.semantic_question_id)
    if catalog_question.target != question.target:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.QUESTION_MISMATCH,
            "clarification question target does not match the Question Catalog",
        )
    if question.options and not isinstance(
        catalog_question.answer_contract, DictionaryAnswerContract
    ):
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.QUESTION_MISMATCH,
            "clarification options do not match the Question Catalog answer contract",
        )
    if question.rule_id is not None:
        decision = rules.evaluate(revision, role_id)
        if (
            not isinstance(decision, AskDecision)
            or decision.rule_id != question.rule_id
            or decision.question_id != question.semantic_question_id
        ):
            raise ClarificationAnswerError(
                ClarificationAnswerErrorCode.QUESTION_NO_LONGER_APPLICABLE,
                "approved rule no longer selects this clarification question",
            )


def _find_previous(previous_results, answer, answer_hash):
    for result in previous_results:
        result = ClarificationAnswerResult.model_validate(result)
        if (
            result.session_id == answer.session_id
            and result.plan_content_hash == answer.plan_content_hash
            and result.clarification_id == answer.clarification_id
        ):
            if result.answer_hash == answer_hash:
                return result
            raise ClarificationAnswerError(
                ClarificationAnswerErrorCode.CONFLICTING_ANSWER,
                "a different answer was already processed for this clarification question",
            )
    return None


def _resolve_decision(question, answer):
    if answer.decision == ClarificationDecision.SELECT_OPTION:
        option = next(
            (item for item in question.options if item.value == answer.selected_option),
            None,
        )
        if option is None:
            raise ClarificationAnswerError(
                ClarificationAnswerErrorCode.INVALID_OPTION,
                "selected option was not offered by the clarification question",
            )
        return option
    if answer.decision == ClarificationDecision.ACCEPT:
        if (
            question.category
            not in {
                ClarificationCategory.PREFERENCE_ACCEPTANCE,
                ClarificationCategory.KNOWLEDGE_RECOMMENDATION,
            }
            or len(question.options) != 1
        ):
            raise ClarificationAnswerError(
                ClarificationAnswerErrorCode.INVALID_DECISION,
                "ACCEPT requires exactly one preference or recommendation option",
            )
        return question.options[0]
    if answer.decision == ClarificationDecision.REJECT and question.category not in {
        ClarificationCategory.PREFERENCE_ACCEPTANCE,
        ClarificationCategory.KNOWLEDGE_RECOMMENDATION,
    }:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.INVALID_DECISION,
            "REJECT is valid only for a preference or recommendation",
        )
    return None


def _parser_proposal(question, option, answer, revision, dictionary):
    parser_target = _PARSER_TARGET.get(question.semantic_question_id)
    category = _CATEGORY_BY_QUESTION.get(question.semantic_question_id)
    if parser_target is None or category is None or option is None:
        return None
    try:
        catalog_entry = dictionary[option.value]
    except KeyError as exc:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.INVALID_OPTION,
            "offered option is absent from the active dictionary",
        ) from exc
    if catalog_entry.lifecycle != EntryLifecycle.ACTIVE or catalog_entry.category != category:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.INVALID_OPTION,
            "offered option no longer matches the active dictionary contract",
        )
    update = CandidateUpdate(
        target=parser_target,
        value=TermCandidate(text=option.label),
    )
    proposal = build_parser_proposal(
        revision,
        expected_revision_id=revision.revision_id,
        source=answer.source,
        locale="en" if question.locale.value == "en" else "ru",
        dictionary=dictionary,
        candidate=ParserCandidate(updates=(update,)),
    )
    if proposal.accepted_updates and proposal.accepted_updates[0].canonical_value != option.value:
        raise ClarificationAnswerError(
            ClarificationAnswerErrorCode.INVALID_OPTION,
            "offered option no longer normalizes to its recorded value",
        )
    return proposal


def _current_state(revision, question):
    design = revision.design
    return {
        QuestionId.CENTER_STONE_SHAPE: design.center_stone.shape,
        QuestionId.CENTER_STONE_DIMENSIONS: design.center_stone.dimensions,
        QuestionId.CENTER_STONE_SETTING: design.center_stone.setting,
        QuestionId.METAL_COLOR: design.metal.color,
    }.get(question.semantic_question_id)


def _result(
    plan,
    question,
    answer,
    *,
    answer_hash,
    option,
    current_revision,
    outcome,
    reason,
    question_resolved,
    new_revision=None,
):
    payload = {
        "answer_version": CLARIFICATION_ANSWER_VERSION,
        "session_id": answer.session_id,
        "plan_content_hash": plan.content_hash,
        "clarification_id": question.clarification_id,
        "semantic_question_id": question.semantic_question_id,
        "decision": answer.decision,
        "selected_option": option,
        "source_candidate_ids": question.source_candidate_ids,
        "source_proposal_ids": question.source_proposal_ids,
        "evidence": question.evidence,
        "target": question.target.value,
        "subject": question.subject.value if question.subject is not None else None,
        "previous_revision_id": current_revision.revision_id,
        "new_revision_id": new_revision.revision_id if new_revision is not None else None,
        "resulting_revision": new_revision,
        "knowledge_package_id": plan.knowledge_package_id,
        "knowledge_artifact_version": plan.knowledge_artifact_version,
        "knowledge_runtime_sha256": plan.knowledge_runtime_sha256,
        "knowledge_validation_report_sha256": plan.knowledge_validation_report_sha256,
        "question_artifact_version": plan.question_artifact_version,
        "rules_artifact_version": plan.rules_artifact_version,
        "outcome": outcome,
        "reason": reason,
        "question_resolved": question_resolved,
        "blocks_progression": not question_resolved
        and question.importance == ClarificationImportance.BLOCKING,
        "answer_hash": answer_hash,
    }
    return ClarificationAnswerResult(**payload, content_hash=_hash(_json(payload)))


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _hash(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
