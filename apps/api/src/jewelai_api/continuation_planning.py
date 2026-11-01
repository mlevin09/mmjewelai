"""Native planning adapters for actual validated F05 plans; no forged Plan1/2."""

from types import SimpleNamespace

from jewelai_domain.dictionary import DictionaryLocale
from jewelai_domain.preservation import anchor_hash, contract_hash, target_state
from jewelai_domain.preservation_release import (
    KeepReleaseOffer,
    KeepReofferBinding,
    anchor_set_hash,
)
from jewelai_domain.questions import QuestionLocale
from jewelai_prompts.final_prompt import _value_text


def native_plan_view(plan):
    """Project existing native evidence from a validated Plan3, without relabelling it."""
    from .continuation_plan import ContinuationPlan

    plan = ContinuationPlan.model_validate(plan)
    native = plan.native_base
    payload = dict(
        _f05_plan=plan,
        plan_id=plan.allocated_current_frame_core.plan_id,
        content_hash=plan.content_hash,
        scope=plan.context.scope,
        design_revision_id=plan.design_revision_id,
        locale=QuestionLocale(plan.locale),
        role_id=plan.role_id,
        questions=native.native_questions,
        rule_decision=native.rule_decision,
        unasked_evidence=plan.unasked_evidence,
        constraint_evidence=plan.constraint_evidence,
        artifact_pins=plan.context.artifact_pins,
        knowledge_package_id=plan.knowledge_package_id,
        knowledge_artifact_version=plan.knowledge_artifact_version,
        knowledge_runtime_sha256=plan.knowledge_runtime_sha256,
        knowledge_validation_report_sha256=plan.knowledge_validation_report_sha256,
        question_artifact_version=plan.question_artifact_version,
        rules_artifact_version=plan.rules_artifact_version,
        enrichment_cycle_number=plan.allocated_current_frame_core.enrichment_cycle_number,
    )
    if plan.context.retained_base == "F":
        payload.update(
            frontier_core=native.frontier_core,
            cause_definitions=native.cause_definitions,
            conflicts=native.conflicts,
        )
    return SimpleNamespace(**payload)


def release_request_label(intent, dictionary, locale):
    field = intent.target.concrete_target
    labels = {
        "material": ("material", "материал"),
        "shape": ("shape", "форма"),
        "cut": ("cut", "огранка"),
        "weight": ("weight", "масса"),
        "dimensions": ("dimensions", "размеры"),
        "setting": ("setting", "закрепка"),
    }
    label = labels[field.split(".")[1]][int(locale == "ru")]
    value = _value_text(
        intent.requested_state.value, dictionary, DictionaryLocale(locale), target=field
    )
    return label, value


def release_offer(
    intent, protection, before, *, previous_head, plan_id, dictionary, locale, previous_offer=None
):
    """An explicit command allocates an offer; GET must never call this writer helper."""
    field = intent.target.concrete_target
    roots = tuple(
        r.root_ref
        for r in sorted(protection.roots, key=lambda r: r.root_ref.evidence_id)
        if any(t.concrete_target == field for t in r.scope_targets)
    )
    state = target_state(before.design, field)
    from jewelai_domain.models import KnownValue
    from jewelai_domain.preservation_release import requested_value_hash

    current = (
        isinstance(state, KnownValue)
        and requested_value_hash(state.value) == intent.requested_value_sha256
    )
    from jewelai_domain.lock_protection import locked_ancestor, state_fields

    locked = locked_ancestor(state_fields(before.design), tuple(field.split("."))) is not None
    actions = ("REJECT",) if current or locked else ("ACCEPT", "REJECT")
    p = dict(
        schema_version="1.0.0",
        intent_id=intent.intent_id,
        previous_offer_ref=dict(id=previous_offer.offer_id, hash=previous_offer.content_hash)
        if previous_offer
        else None,
        previous_binding_ref=dict(
            id=previous_offer.binding.binding_id, hash=previous_offer.binding.content_hash
        )
        if previous_offer
        else None,
        owning_plan_id=plan_id,
        source_head=previous_head,
        current_before_state_sha256=anchor_hash(state),
        anchor_set_sha256=anchor_set_hash(protection),
        applicable_keep_roots=roots,
        allowed_decisions=actions,
    )
    p["binding_id"] = contract_hash("jewelai.ReofferBinding/1.0.0", p)
    binding = KeepReofferBinding(**p, content_hash=contract_hash("jewelai.ReofferBinding/1.0.0", p))
    label, value = release_request_label(intent, dictionary, locale)
    text = (
        (
            "Close this request and preserve the current center stone."
            if locale == "en"
            else "Закрыть этот запрос и сохранить текущий центральный камень."
        )
        if current
        else (
            (
                f"Change the preserved center-stone {label} to {value}? "
                "Keep all other protected properties unchanged."
            )
            if locale == "en"
            else (
                f"Изменить защищённое свойство центрального камня «{label}» на «{value}»? "
                "Остальные защищённые свойства сохранить."
            )
        )
    )
    if locked:
        text = (
            "This field is locked. Close the pending request; preserve its current value."
            if locale == "en"
            else "Поле заблокировано. Закрыть ожидающий запрос и сохранить текущее значение."
        )
    p = dict(
        schema_version="1.0.0",
        intent_id=intent.intent_id,
        binding=binding,
        target=intent.target,
        requested_value_sha256=intent.requested_value_sha256,
        locale=locale,
        rendered_question=text,
        allowed_decisions=actions,
        owning_plan_id=plan_id,
    )
    p["offer_id"] = contract_hash("jewelai.Offer/1.0.0", p)
    return KeepReleaseOffer(**p, content_hash=contract_hash("jewelai.Offer/1.0.0", p))


def correction_native_plan(
    service, plan, result, *, plan_id, record_id, constraints, offer_history=()
):
    """Reuse existing deterministic planners, returning only native base evidence."""
    from .clarification import plan_clarifications
    from .clarification_v2 import AcceptedResultTrigger
    from .continuation_evaluation import ParsedEvaluationV3
    from .continuation_plan import NativeFPlanEvidence, NativeLPlanEvidence
    from .f04_frontier import advance_frontier, relevant_reoffers
    from .f04_planning import plan_f04

    old = native_plan_view(plan)
    revision = result.authoritative_revision
    evaluation = result.post_transition_evaluation
    if plan.context.retained_base == "L":

        def finish(**payload):
            base = NativeLPlanEvidence(
                retained_base="L",
                rule_decision=payload["rule_decision"],
                native_questions=payload["questions"],
                native_decision_audit=plan.native_base.native_decision_audit,
            )
            return base, payload["unasked_evidence"]

        return plan_clarifications(
            revision,
            evaluation,
            role_id=plan.role_id,
            dictionary=service.artifacts.dictionary,
            questions=service.artifacts.questions,
            rules=service.artifacts.rules,
            constraint_evidence=constraints,
            _enrichment_reader=ParsedEvaluationV3,
            _canonical_revision_only=True,
            _plan_builder=finish,
            _rule_decision_override=service.artifacts.rules.evaluate(revision, plan.role_id),
        )
    states = advance_frontier(old, result, record_id=record_id, result_kind="correction")
    changes = relevant_reoffers(
        old,
        result,
        service.repository.get_revision(
            plan.context.scope.session_id,
            result.previous_revision_id,
            plan.context.scope.organization_id,
        ),
        revision,
        record_id=record_id,
        projected_states=states,
        offer_history=offer_history,
    )

    def finish(**payload):
        base = NativeFPlanEvidence(
            retained_base="F",
            rule_decision=payload["rule_decision"],
            native_questions=payload["questions"],
            conflicts=payload["conflicts"],
            cause_definitions=payload["cause_definitions"],
            frontier_core=payload["frontier_core"],
            availability_overlay=evaluation.enrichment_result.availability_overlay,
        )
        return base, payload["unasked_evidence"]

    return plan_f04(
        revision,
        evaluation,
        artifacts=service.artifacts,
        role_id=plan.role_id,
        plan_id=plan_id,
        cycle_id=result.next_enrichment_cycle_id,
        cycle_number=result.next_enrichment_cycle_number,
        trigger=AcceptedResultTrigger(
            kind="correction",
            record_id=record_id,
            content_hash=result.content_hash,
            previous_plan_id=old.plan_id,
            previous_plan_hash=old.content_hash,
            message_id=result.request.message_id,
            message_content_sha256=result.source_message_sha256,
        ),
        previous_plan=old,
        current_states=states,
        constraint_evidence=constraints,
        offer_history=offer_history,
        relevant_changes=changes,
        _plan_builder=finish,
        _enrichment_reader=ParsedEvaluationV3,
        _canonical_revision_only=True,
    )


def pending_descriptions(repo, plan, dictionary):
    """Called only after full interval replay; logical requests are not inferred."""
    from .continuation_results import ContinuationCorrectionResult

    known = {}
    for row in repo.list_user_corrections(
        plan.context.scope.session_id, plan.context.scope.organization_id
    ):
        if row.result_payload.get("correction_version") != "3.0.0":
            continue
        result = ContinuationCorrectionResult.model_validate(row.result_payload)
        for intent in result.keep_intents:
            if intent.context != plan.context:
                raise ValueError("Pending intent has another retained context")
            known[intent.intent_id] = intent
    lines = []
    for pending in plan.protection_projection.pending_requests:
        if pending.intent_id not in known:
            raise ValueError("Pending projection has no actual sourced intent")
        intent = known[pending.intent_id]
        label, value = release_request_label(intent, dictionary, plan.locale)
        from jewelai_domain.models import KnownValue
        from jewelai_domain.preservation_release import requested_value_hash

        current = target_state(
            repo.get_revision(
                plan.context.scope.session_id,
                plan.allocated_current_frame_core.revision_id,
                plan.context.scope.organization_id,
            ).design,
            intent.target.concrete_target,
        )
        if (
            isinstance(current, KnownValue)
            and requested_value_hash(current.value) == intent.requested_value_sha256
        ):
            lines.append(
                (
                    f"Pending request matches current center-stone {label}: {value}; "
                    "explicit closure is required."
                )
                if plan.locale == "en"
                else (
                    f"Ожидающий запрос совпадает с текущим свойством «{label}»: {value}; "
                    "требуется явное закрытие."
                )
            )
            continue
        lines.append(
            f"Pending request, not applied: center-stone {label} → {value}."
            if plan.locale == "en"
            else f"Ожидающий запрос, не применён: {label} центрального камня → {value}."
        )
    return tuple(lines)


class NativePlanViewReader:
    """Recreate native inputs from their actual Plan3, never accept a fake Plan2."""

    @staticmethod
    def model_validate(view):
        return native_plan_view(view._f05_plan)


def native_offers(prefix, verified, sid, oid, base):
    from .clarification import ClarificationPlan
    from .clarification_v2 import ClarificationPlanV2

    reader = ClarificationPlanV2 if base == "F" else ClarificationPlan
    old = [reader.model_validate(p.plan_payload) for p in prefix.list_clarification_plans(sid, oid)]
    return tuple(q for p in old for q in p.questions) + tuple(
        q for _, p, _ in verified for q in p.native_base.native_questions
    )


def answer_native_plan(service, previous, result, revision, *, plan_id, cycle_id, offer_history):
    from .clarification import continue_clarification_plan
    from .clarification_v2 import AcceptedResultTrigger
    from .continuation_plan import NativeFPlanEvidence, NativeLPlanEvidence
    from .f04_frontier import advance_frontier, relevant_reoffers
    from .f04_planning import plan_f04

    old = native_plan_view(previous)
    kind = result.answer_kind
    answered = (result.clarification_id,) if kind == "NATIVE" else ()
    if kind == "KEEP_RELEASE" and result.outcome == "APPLIED":
        target = result.keep_decision.accepted_target.target.concrete_target
        answered = tuple(
            q.clarification_id
            for q in old.questions
            if q.category == "required_information"
            and (
                q.target.concrete_target if hasattr(q.target, "concrete_target") else q.target.value
            )
            == target
        )
    if previous.context.retained_base == "L":

        def finish(**payload):
            return NativeLPlanEvidence(
                retained_base="L",
                rule_decision=payload["rule_decision"],
                native_questions=payload["questions"],
                native_decision_audit=previous.native_base.native_decision_audit,
            ), payload["unasked_evidence"]

        return continue_clarification_plan(
            old,
            revision,
            answered_clarification_ids=answered,
            questions=service.artifacts.questions,
            rules=service.artifacts.rules,
            _plan_reader=NativePlanViewReader,
            _plan_builder=finish,
        )
    states = advance_frontier(
        old,
        result,
        record_id=result.answer_id,
        result_kind="clarification",
        _native_answer=kind == "NATIVE",
    )
    before = service.repository.get_revision(
        previous.context.scope.session_id,
        result.previous_revision_id,
        previous.context.scope.organization_id,
    )
    relevant = relevant_reoffers(
        old,
        result,
        before,
        revision,
        record_id=result.answer_id,
        projected_states=states,
        offer_history=offer_history,
    )

    def finish(**payload):
        return NativeFPlanEvidence(
            retained_base="F",
            rule_decision=payload["rule_decision"],
            native_questions=payload["questions"],
            conflicts=payload["conflicts"],
            cause_definitions=payload["cause_definitions"],
            frontier_core=payload["frontier_core"],
            availability_overlay=result.next_enrichment_result.native.availability_overlay,
        ), payload["unasked_evidence"]

    trigger = AcceptedResultTrigger(
        kind="answer",
        record_id=result.answer_id,
        content_hash=result.content_hash,
        previous_plan_id=old.plan_id,
        previous_plan_hash=old.content_hash,
        message_id=result.request.message_id,
        message_content_sha256=result.message_sha256,
    )
    return plan_f04(
        revision,
        result.next_enrichment_result.native,
        artifacts=service.artifacts,
        role_id=previous.role_id,
        plan_id=plan_id,
        cycle_id=cycle_id,
        cycle_number=previous.allocated_current_frame_core.enrichment_cycle_number + 1,
        trigger=trigger,
        previous_plan=old,
        current_states=states,
        constraint_evidence=previous.constraint_evidence,
        answered_ids=answered,
        offer_history=offer_history,
        relevant_changes=relevant,
        _plan_builder=finish,
        _previous_plan_reader=NativePlanViewReader,
    )
