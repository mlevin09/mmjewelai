"""Deterministic clarification planning over verified first-enrichment evidence.

This internal composition boundary is intentionally not routed by FastAPI. It reuses the
versioned Question Catalog and Rules Engine, and never applies proposals or mutates Product
State.
"""

import hashlib
import json
from enum import StrEnum
from typing import Literal

from jewelai_domain.dictionary import DictionaryLocale, DictionaryRegistry, EntryLifecycle
from jewelai_domain.knowledge_policy import RuntimeProvenance
from jewelai_domain.models import ImmutableModel, KnownValue, Text
from jewelai_domain.models_v1_1 import AnyDesignRevision, validate_design_revision
from jewelai_domain.questions import QuestionCatalog, QuestionId, QuestionLocale, SchemaTarget
from jewelai_domain.roles import RoleId
from jewelai_domain.rules import AskDecision, BlockDecision, RuleDecision, RuleRegistry
from jewelai_parser import CandidateSubject, StructuredTarget
from jewelai_prompts import FinalPromptConstraintEvidence
from pydantic import Field, model_validator

from .parsed_enrichment import (
    CandidateDispositionReason,
    ParsedCandidateEnrichmentResult,
)

CLARIFICATION_PLAN_VERSION = "1.1.0"


class ClarificationPlanInputError(ValueError):
    """Raised when immutable planning inputs do not share verified lineage."""


class ClarificationCategory(StrEnum):
    MATERIAL_AMBIGUITY = "material_ambiguity"
    PREFERENCE_ACCEPTANCE = "preference_acceptance"
    KNOWLEDGE_RECOMMENDATION = "knowledge_recommendation"
    REQUIRED_INFORMATION = "required_information"


class ClarificationImportance(StrEnum):
    BLOCKING = "blocking"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class UnaskedReason(StrEnum):
    NONCRITICAL_UNKNOWN = "noncritical_unknown"
    UNSUPPORTED_ANSWER_PATH = "unsupported_answer_path"
    CONSTRAINT_RETAINED = "constraint_retained"
    TARGET_ALREADY_CONFIRMED = "target_already_confirmed"
    NO_VERIFIED_CHOICE = "no_verified_choice"


class ClarificationEvidence(ImmutableModel):
    candidate_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: Text


class ClarificationOption(ImmutableModel):
    value: str
    label: Text
    source_ids: tuple[str, ...] = ()


class ClarificationQuestion(ImmutableModel):
    clarification_id: str
    semantic_question_id: QuestionId
    category: ClarificationCategory
    importance: ClarificationImportance
    priority: int = Field(ge=0, le=10_000)
    text: Text
    locale: QuestionLocale
    target: SchemaTarget
    subject: CandidateSubject | None = None
    source_candidate_ids: tuple[str, ...] = ()
    source_proposal_ids: tuple[str, ...] = ()
    evidence: tuple[ClarificationEvidence, ...] = ()
    options: tuple[ClarificationOption, ...] = ()
    reason: Text
    design_revision_id: str
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: str
    knowledge_validation_report_sha256: str
    question_artifact_version: str
    rules_artifact_version: str
    rule_id: str | None = None
    rule_version: str | None = None


class UnaskedClarificationEvidence(ImmutableModel):
    candidate_id: str
    disposition_reason: CandidateDispositionReason
    reason: UnaskedReason


class ClarificationPlan(ImmutableModel):
    plan_version: Literal["1.1.0"] = CLARIFICATION_PLAN_VERSION
    design_revision_id: str
    knowledge_package_id: str
    knowledge_artifact_version: str
    knowledge_runtime_sha256: str
    knowledge_validation_report_sha256: str
    question_artifact_version: str
    rules_artifact_version: str
    locale: QuestionLocale
    role_id: RoleId
    rule_decision: RuleDecision
    questions: tuple[ClarificationQuestion, ...]
    unasked_evidence: tuple[UnaskedClarificationEvidence, ...]
    constraint_evidence: tuple[FinalPromptConstraintEvidence, ...]
    can_continue_without_answers: bool
    content_hash: str

    @model_validator(mode="after")
    def validate_hash_and_progression(self):
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if self.content_hash != _hash(payload):
            raise ValueError("clarification plan content hash mismatch")
        expected = not isinstance(self.rule_decision, BlockDecision) and not any(
            item.importance == ClarificationImportance.BLOCKING for item in self.questions
        )
        if self.can_continue_without_answers != expected:
            raise ValueError("clarification progression flag does not match blocking evidence")
        evidence_ids = tuple(item.evidence_id for item in self.constraint_evidence)
        if evidence_ids != tuple(sorted(evidence_ids)) or len(evidence_ids) != len(
            set(evidence_ids)
        ):
            raise ValueError("constraint evidence must use unique stable evidence-ID order")
        return self


_TARGET_QUESTION = {
    StructuredTarget.CENTER_STONE_SHAPE: QuestionId.CENTER_STONE_SHAPE,
    StructuredTarget.CENTER_STONE_DIMENSIONS: QuestionId.CENTER_STONE_DIMENSIONS,
    StructuredTarget.CENTER_STONE_SETTING: QuestionId.CENTER_STONE_SETTING,
    StructuredTarget.METAL_COLOR: QuestionId.METAL_COLOR,
    StructuredTarget.SIDE_STONE_QUANTITY: QuestionId.SIDE_STONE_QUANTITY,
}

_SCHEMA_QUESTION = {
    SchemaTarget.CENTER_STONE_SHAPE: QuestionId.CENTER_STONE_SHAPE,
    SchemaTarget.CENTER_STONE_DIMENSIONS: QuestionId.CENTER_STONE_DIMENSIONS,
    SchemaTarget.CENTER_STONE_SETTING: QuestionId.CENTER_STONE_SETTING,
    SchemaTarget.METAL_COLOR: QuestionId.METAL_COLOR,
    SchemaTarget.SIDE_STONE_QUANTITY: QuestionId.SIDE_STONE_QUANTITY,
}

_UNSUPPORTED_REASONS = {
    CandidateDispositionReason.PARSER_REJECTED,
    CandidateDispositionReason.SIDE_STONE_GROUP_MISSING,
    CandidateDispositionReason.SIDE_STONE_GROUP_AMBIGUOUS,
    CandidateDispositionReason.TARGET_NOT_SUPPORTED_BY_PARSER,
    CandidateDispositionReason.COMPONENT_TARGET_NOT_REPRESENTABLE,
    CandidateDispositionReason.DUPLICATE_TARGET_CANDIDATES,
}


def plan_clarifications(
    revision: AnyDesignRevision | object,
    enrichment: ParsedCandidateEnrichmentResult,
    *,
    role_id: RoleId | str,
    dictionary: DictionaryRegistry,
    questions: QuestionCatalog,
    rules: RuleRegistry,
    constraint_evidence: tuple[FinalPromptConstraintEvidence, ...] = (),
) -> ClarificationPlan:
    """Build a minimal immutable plan without accepting evidence or changing Product State."""

    revision = validate_design_revision(revision)
    enrichment = ParsedCandidateEnrichmentResult.model_validate(enrichment)
    role_id = RoleId(role_id)
    constraint_evidence = tuple(
        sorted(
            (FinalPromptConstraintEvidence.model_validate(item) for item in constraint_evidence),
            key=lambda item: item.evidence_id,
        )
    )
    result = enrichment.enrichment_result
    if result.design_revision_id != str(revision.revision_id):
        raise ClarificationPlanInputError("enrichment and Product State revision do not match")
    if result.knowledge_validation_report_sha256 is None:
        raise ClarificationPlanInputError(
            "clarification planning requires a verified ACTIVE release"
        )
    if enrichment.parse_result.dictionary_artifact_version != dictionary.artifact_version:
        raise ClarificationPlanInputError("parse and dictionary artifact versions do not match")
    parse_release = (
        enrichment.parse_result.knowledge_package_id,
        enrichment.parse_result.knowledge_artifact_version,
        enrichment.parse_result.knowledge_runtime_sha256,
    )
    result_release = (
        result.knowledge_package_id,
        result.knowledge_artifact_version,
        result.knowledge_runtime_sha256,
    )
    if parse_release[0] is not None and parse_release != result_release:
        raise ClarificationPlanInputError(
            "parse and enrichment Knowledge release identities do not match"
        )
    if rules.artifact_version == "" or questions.artifact_version == "":
        raise ClarificationPlanInputError("question and rules artifacts must be versioned")

    locale = QuestionLocale(enrichment.parse_result.requested_locale)
    effective_revision = _effective_revision(revision, enrichment)
    rule_decision = rules.evaluate(effective_revision, role_id)
    rule_question_id = rule_decision.question_id if isinstance(rule_decision, AskDecision) else None

    grouped: dict[tuple[QuestionId, ClarificationCategory, CandidateSubject | None], list] = {}
    unasked: list[UnaskedClarificationEvidence] = []
    for disposition in enrichment.dispositions:
        question_id = _TARGET_QUESTION.get(disposition.candidate.target)
        if disposition.reason == CandidateDispositionReason.AMBIGUOUS_CANDIDATE:
            category = ClarificationCategory.MATERIAL_AMBIGUITY
        elif disposition.reason == CandidateDispositionReason.PREFERENCE_REQUIRES_ACCEPTANCE:
            category = ClarificationCategory.PREFERENCE_ACCEPTANCE
        else:
            _record_unasked(disposition, question_id, unasked)
            continue
        if question_id is None:
            unasked.append(_unasked(disposition, UnaskedReason.UNSUPPORTED_ANSWER_PATH))
            continue
        if question_id == QuestionId.SIDE_STONE_QUANTITY and len(revision.design.side_stones) != 1:
            unasked.append(_unasked(disposition, UnaskedReason.UNSUPPORTED_ANSWER_PATH))
            continue
        if _is_confirmed(revision, questions.get_question(question_id).target):
            unasked.append(_unasked(disposition, UnaskedReason.TARGET_ALREADY_CONFIRMED))
            continue
        grouped.setdefault((question_id, category, disposition.candidate.subject), []).append(
            disposition
        )

    planned: list[ClarificationQuestion] = []
    consumed_rule = False
    for key, dispositions in grouped.items():
        question_id, category, subject = key
        options = _candidate_options(dispositions, dictionary, locale)
        if category == ClarificationCategory.MATERIAL_AMBIGUITY and len(options) < 2:
            unasked.extend(
                _unasked(item, UnaskedReason.NO_VERIFIED_CHOICE) for item in dispositions
            )
            continue
        rule = rule_decision if rule_question_id == question_id else None
        consumed_rule = consumed_rule or rule is not None
        importance = (
            ClarificationImportance.BLOCKING
            if rule is not None
            else (
                ClarificationImportance.RECOMMENDED
                if category == ClarificationCategory.MATERIAL_AMBIGUITY
                else ClarificationImportance.OPTIONAL
            )
        )
        planned.append(
            _question(
                enrichment,
                questions=questions,
                rules=rules,
                role_id=role_id,
                locale=locale,
                question_id=question_id,
                category=category,
                importance=importance,
                priority=rule.priority if rule is not None else 0,
                subject=subject,
                dispositions=tuple(dispositions),
                options=options,
                rule=rule,
            )
        )

    for decision in result.decisions:
        proposal = decision.proposal
        if proposal.provenance != RuntimeProvenance.JEWELAI_RECOMMENDED:
            continue
        question_id = _question_for_concrete_target(proposal.target)
        if question_id is None:
            continue
        schema_target = questions.get_question(question_id).target
        if _is_confirmed(revision, schema_target):
            continue
        options = _proposal_options(proposal.value, proposal.source_id, dictionary, locale)
        planned.append(
            _question(
                enrichment,
                questions=questions,
                rules=rules,
                role_id=role_id,
                locale=locale,
                question_id=question_id,
                category=ClarificationCategory.KNOWLEDGE_RECOMMENDATION,
                importance=ClarificationImportance.RECOMMENDED,
                priority=0,
                subject=None,
                dispositions=(),
                options=options,
                proposal_ids=(proposal.source_id,),
                rule=None,
            )
        )

    if isinstance(rule_decision, AskDecision) and not consumed_rule:
        planned.append(
            _question(
                enrichment,
                questions=questions,
                rules=rules,
                role_id=role_id,
                locale=locale,
                question_id=rule_decision.question_id,
                category=ClarificationCategory.REQUIRED_INFORMATION,
                importance=ClarificationImportance.BLOCKING,
                priority=rule_decision.priority,
                subject=None,
                dispositions=(),
                options=(),
                rule=rule_decision,
            )
        )

    deduplicated = {item.clarification_id: item for item in planned}
    ordered = tuple(
        sorted(
            deduplicated.values(),
            key=lambda item: (
                -_importance_rank(item.importance),
                -item.priority,
                item.semantic_question_id.value,
                item.clarification_id,
            ),
        )
    )
    ordered_unasked = tuple(
        sorted(unasked, key=lambda item: (item.candidate_id, item.reason.value))
    )
    payload = {
        "plan_version": CLARIFICATION_PLAN_VERSION,
        "design_revision_id": str(revision.revision_id),
        "knowledge_package_id": result.knowledge_package_id,
        "knowledge_artifact_version": result.knowledge_artifact_version,
        "knowledge_runtime_sha256": result.knowledge_runtime_sha256,
        "knowledge_validation_report_sha256": result.knowledge_validation_report_sha256,
        "question_artifact_version": questions.artifact_version,
        "rules_artifact_version": rules.artifact_version,
        "locale": locale,
        "role_id": role_id,
        "rule_decision": rule_decision,
        "questions": ordered,
        "unasked_evidence": ordered_unasked,
        "constraint_evidence": constraint_evidence,
        "can_continue_without_answers": not isinstance(rule_decision, BlockDecision)
        and not any(item.importance == ClarificationImportance.BLOCKING for item in ordered),
    }
    return ClarificationPlan(**payload, content_hash=_hash(_json(payload)))


def continue_clarification_plan(
    previous_plan: ClarificationPlan,
    revision: AnyDesignRevision | object,
    *,
    answered_clarification_ids: tuple[str, ...],
    questions: QuestionCatalog,
    rules: RuleRegistry,
) -> ClarificationPlan:
    """Advance one durable plan without replaying parsing or accepting client plan content."""

    plan = ClarificationPlan.model_validate(previous_plan)
    revision = validate_design_revision(revision)
    answered = set(answered_clarification_ids)
    rule_decision = rules.evaluate(revision, plan.role_id)
    retained = [
        _rebind_question(item, revision.revision_id)
        for item in plan.questions
        if item.clarification_id not in answered and not _is_confirmed(revision, item.target)
    ]
    if isinstance(rule_decision, AskDecision) and not any(
        item.semantic_question_id == rule_decision.question_id for item in retained
    ):
        retained.append(
            _rule_question_from_plan(
                plan,
                revision.revision_id,
                rule_decision,
                questions=questions,
                rules=rules,
            )
        )
    ordered = tuple(
        sorted(
            retained,
            key=lambda item: (
                -_importance_rank(item.importance),
                -item.priority,
                item.semantic_question_id.value,
                item.clarification_id,
            ),
        )
    )
    payload = {
        "plan_version": CLARIFICATION_PLAN_VERSION,
        "design_revision_id": str(revision.revision_id),
        "knowledge_package_id": plan.knowledge_package_id,
        "knowledge_artifact_version": plan.knowledge_artifact_version,
        "knowledge_runtime_sha256": plan.knowledge_runtime_sha256,
        "knowledge_validation_report_sha256": plan.knowledge_validation_report_sha256,
        "question_artifact_version": questions.artifact_version,
        "rules_artifact_version": rules.artifact_version,
        "locale": plan.locale,
        "role_id": plan.role_id,
        "rule_decision": rule_decision,
        "questions": ordered,
        "unasked_evidence": plan.unasked_evidence,
        "constraint_evidence": plan.constraint_evidence,
        "can_continue_without_answers": not isinstance(rule_decision, BlockDecision)
        and not any(item.importance == ClarificationImportance.BLOCKING for item in ordered),
    }
    return ClarificationPlan(**payload, content_hash=_hash(_json(payload)))


def _rebind_question(question: ClarificationQuestion, revision_id) -> ClarificationQuestion:
    payload = question.model_dump(mode="json")
    payload["design_revision_id"] = str(revision_id)
    identity = dict(payload)
    identity.pop("clarification_id")
    payload["clarification_id"] = f"clarification_{_hash(identity)[:24]}"
    return ClarificationQuestion.model_validate(payload)


def _rule_question_from_plan(plan, revision_id, rule, *, questions, rules):
    rendered = questions.render(rule.question_id, plan.role_id, plan.locale.value)
    identity = {
        "design_revision_id": str(revision_id),
        "knowledge_package_id": plan.knowledge_package_id,
        "knowledge_artifact_version": plan.knowledge_artifact_version,
        "knowledge_runtime_sha256": plan.knowledge_runtime_sha256,
        "knowledge_validation_report_sha256": plan.knowledge_validation_report_sha256,
        "question_artifact_version": questions.artifact_version,
        "rules_artifact_version": rules.artifact_version,
        "semantic_question_id": rule.question_id,
        "category": ClarificationCategory.REQUIRED_INFORMATION,
        "locale": plan.locale,
        "rule_id": rule.rule_id,
        "rule_version": rule.rule_version,
    }
    return ClarificationQuestion(
        clarification_id=f"clarification_{_hash(_json(identity))[:24]}",
        semantic_question_id=rule.question_id,
        category=ClarificationCategory.REQUIRED_INFORMATION,
        importance=ClarificationImportance.BLOCKING,
        priority=rule.priority,
        text=rendered.wording,
        locale=plan.locale,
        target=rendered.target,
        reason=_reason(ClarificationCategory.REQUIRED_INFORMATION, rule),
        design_revision_id=str(revision_id),
        knowledge_package_id=plan.knowledge_package_id,
        knowledge_artifact_version=plan.knowledge_artifact_version,
        knowledge_runtime_sha256=plan.knowledge_runtime_sha256,
        knowledge_validation_report_sha256=plan.knowledge_validation_report_sha256,
        question_artifact_version=questions.artifact_version,
        rules_artifact_version=rules.artifact_version,
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
    )


def _record_unasked(disposition, question_id, unasked):
    reason = disposition.reason
    if reason in {
        CandidateDispositionReason.UNRESOLVED_CANDIDATE,
        CandidateDispositionReason.ALREADY_CURRENT,
    }:
        unasked.append(_unasked(disposition, UnaskedReason.NONCRITICAL_UNKNOWN))
    elif reason in {
        CandidateDispositionReason.PROHIBITION_RETAINED,
        CandidateDispositionReason.PRESERVATION_RETAINED,
    }:
        unasked.append(_unasked(disposition, UnaskedReason.CONSTRAINT_RETAINED))
    elif reason in _UNSUPPORTED_REASONS or question_id is None:
        unasked.append(_unasked(disposition, UnaskedReason.UNSUPPORTED_ANSWER_PATH))


def _unasked(disposition, reason):
    return UnaskedClarificationEvidence(
        candidate_id=disposition.candidate.candidate_id,
        disposition_reason=disposition.reason,
        reason=reason,
    )


def _effective_revision(revision, enrichment):
    payload = revision.model_dump(mode="json")
    payload["design"] = enrichment.parser_proposal.proposed_design.model_dump(mode="json")
    return validate_design_revision(payload)


def _is_confirmed(revision, target):
    design = revision.design
    if target == SchemaTarget.SIDE_STONE_QUANTITY:
        return len(design.side_stones) != 1 or (
            isinstance(design.side_stones[0].quantity, KnownValue)
            and design.side_stones[0].quantity.confirmed
        )
    state = {
        SchemaTarget.CENTER_STONE_SHAPE: design.center_stone.shape,
        SchemaTarget.CENTER_STONE_DIMENSIONS: design.center_stone.dimensions,
        SchemaTarget.CENTER_STONE_SETTING: design.center_stone.setting,
        SchemaTarget.METAL_COLOR: design.metal.color,
    }.get(target)
    return isinstance(state, KnownValue) and state.confirmed


def _candidate_options(dispositions, dictionary, locale):
    sources: dict[str, set[str]] = {}
    for disposition in dispositions:
        for value in disposition.candidate.normalized_values:
            try:
                entry = dictionary[value]
            except KeyError:
                continue
            if entry.lifecycle == EntryLifecycle.ACTIVE:
                sources.setdefault(value, set()).add(disposition.candidate.candidate_id)
    return tuple(
        ClarificationOption(
            value=value,
            label=dictionary[value].canonical_terms.for_locale(DictionaryLocale(locale.value)),
            source_ids=tuple(sorted(source_ids)),
        )
        for value, source_ids in sorted(sources.items())
    )


def _proposal_options(value, source_id, dictionary, locale):
    if not isinstance(value, str):
        return ()
    try:
        entry = dictionary[value]
    except KeyError:
        return ()
    if entry.lifecycle != EntryLifecycle.ACTIVE:
        return ()
    return (
        ClarificationOption(
            value=value,
            label=entry.canonical_terms.for_locale(DictionaryLocale(locale.value)),
            source_ids=(source_id,),
        ),
    )


def _question(
    enrichment,
    *,
    questions,
    rules,
    role_id,
    locale,
    question_id,
    category,
    importance,
    priority,
    subject,
    dispositions,
    options,
    proposal_ids=(),
    rule,
):
    rendered = questions.render(question_id, role_id, locale.value)
    candidate_ids = tuple(sorted(item.candidate.candidate_id for item in dispositions))
    evidence = tuple(
        ClarificationEvidence(
            candidate_id=item.candidate.candidate_id,
            start=item.candidate.evidence.start,
            end=item.candidate.evidence.end,
            text=item.candidate.evidence.text,
        )
        for item in sorted(dispositions, key=lambda item: item.candidate.candidate_id)
    )
    result = enrichment.enrichment_result
    identity = {
        "design_revision_id": result.design_revision_id,
        "knowledge_package_id": result.knowledge_package_id,
        "knowledge_artifact_version": result.knowledge_artifact_version,
        "knowledge_runtime_sha256": result.knowledge_runtime_sha256,
        "knowledge_validation_report_sha256": result.knowledge_validation_report_sha256,
        "question_artifact_version": questions.artifact_version,
        "rules_artifact_version": rules.artifact_version,
        "semantic_question_id": question_id,
        "category": category,
        "locale": locale,
        "subject": subject,
        "source_candidate_ids": candidate_ids,
        "source_proposal_ids": tuple(sorted(proposal_ids)),
        "options": options,
        "rule_id": rule.rule_id if rule is not None else None,
        "rule_version": rule.rule_version if rule is not None else None,
    }
    clarification_id = f"clarification_{_hash(_json(identity))[:24]}"
    return ClarificationQuestion(
        clarification_id=clarification_id,
        semantic_question_id=question_id,
        category=category,
        importance=importance,
        priority=priority,
        text=_wording(rendered.wording, category, subject, options, locale),
        locale=locale,
        target=rendered.target,
        subject=subject,
        source_candidate_ids=candidate_ids,
        source_proposal_ids=tuple(sorted(proposal_ids)),
        evidence=evidence,
        options=options,
        reason=_reason(category, rule),
        design_revision_id=result.design_revision_id,
        knowledge_package_id=result.knowledge_package_id,
        knowledge_artifact_version=result.knowledge_artifact_version,
        knowledge_runtime_sha256=result.knowledge_runtime_sha256,
        knowledge_validation_report_sha256=result.knowledge_validation_report_sha256,
        question_artifact_version=questions.artifact_version,
        rules_artifact_version=rules.artifact_version,
        rule_id=rule.rule_id if rule is not None else None,
        rule_version=rule.rule_version if rule is not None else None,
    )


def _wording(default, category, subject, options, locale):
    if not options:
        return default
    labels = [item.label for item in options]
    if locale == QuestionLocale.RU:
        joined = _join(labels, "или")
        subject_text = {
            CandidateSubject.CENTER_STONE: "центрального камня",
            CandidateSubject.PRODUCT_BODY: "металла изделия",
        }.get(subject, "этого элемента")
        if category == ClarificationCategory.MATERIAL_AMBIGUITY:
            return f"Какой вариант вы предпочитаете для {subject_text}: {joined}?"
        return f"Хотите использовать {joined} для {subject_text}?"
    joined = _join(labels, "or")
    subject_text = {
        CandidateSubject.CENTER_STONE: "the center stone",
        CandidateSubject.PRODUCT_BODY: "the product metal",
    }.get(subject, "this design element")
    if category == ClarificationCategory.MATERIAL_AMBIGUITY:
        return f"Which option would you prefer for {subject_text}: {joined}?"
    return f"Would you like to use {joined} for {subject_text}?"


def _join(items, conjunction):
    if len(items) < 2:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def _reason(category, rule):
    if rule is not None:
        return f"Approved rule {rule.rule_id} requires this supported clarification."
    return {
        ClarificationCategory.MATERIAL_AMBIGUITY: "Verified evidence contains multiple choices.",
        ClarificationCategory.PREFERENCE_ACCEPTANCE: "A preference requires explicit acceptance.",
        ClarificationCategory.KNOWLEDGE_RECOMMENDATION: (
            "A Knowledge Library recommendation requires explicit acceptance."
        ),
        ClarificationCategory.REQUIRED_INFORMATION: "An approved rule requires this information.",
    }[category]


def _question_for_concrete_target(target):
    for schema_target, question_id in _SCHEMA_QUESTION.items():
        if target == schema_target.value:
            return question_id
    return None


def _importance_rank(value):
    return {
        ClarificationImportance.BLOCKING: 3,
        ClarificationImportance.RECOMMENDED: 2,
        ClarificationImportance.OPTIONAL: 1,
    }[value]


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


def _hash(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
