"""Exact F04 accepted-target evidence and causal transitions.

These functions do not infer acceptance from Matrix outcomes. Their callers must
commit via repository CAS; restoration independently checks the persisted records,
canonical snapshots, source Messages and exact previous plan/cycle lineage.
"""

from jewelai_domain.clarification_state import AnswerReference, ResolutionReference, evidence_hash
from jewelai_domain.models import KnownValue
from jewelai_domain.rules import _gap_state

from .clarification_v2 import AcceptedTargetEvidence, RelevantChangeReference, ResolutionAssertion
from .f04_planning import canonical_target, target_state


def accepted_target(
    before, after, concrete_target, *, scope, source_message_id, candidate_ids, normalization_refs
):
    target = canonical_target(before, concrete_target, scope=scope)
    old, new = target_state(before, target), target_state(after, target)
    if not isinstance(new, KnownValue):
        raise ValueError("Accepted target has no canonical value")
    return AcceptedTargetEvidence(
        target=target,
        source_message_id=source_message_id,
        source_candidate_ids=tuple(candidate_ids),
        normalization_refs=tuple(normalization_refs),
        before_revision_id=before.revision_id,
        before_state_sha256=evidence_hash(old),
        after_revision_id=after.revision_id,
        after_state_sha256=evidence_hash(new),
        accepted_dictionary_value=new.value if isinstance(new.value, str) else None,
        transition="APPLIED" if before.revision_id != after.revision_id else "NO_CHANGE",
    )


def resolving_assertions(
    plan, accepted, after, *, method, question_id=None, rejected=False, source_message_id=None
):
    assertions = []
    states = {s.cause_id: s for s in plan.frontier_core.cause_states}
    question = next((q for q in plan.questions if q.clarification_id == question_id), None)
    for cause in plan.cause_definitions:
        if states[cause.cause_id].status != "OPEN":
            continue
        if rejected:
            if (
                question is not None
                and question.cause_id == cause.cause_id
                and cause.kind in {"preference_offer", "knowledge_offer"}
            ):
                assertions.append(
                    ResolutionAssertion(
                        cause_id=cause.cause_id,
                        target=cause.target,
                        source_message_id=source_message_id,
                        accepted_target_evidence_index=None,
                        method="offer_rejected",
                        disposition="rejected",
                        reason_code="user_rejected_exact_offer",
                        resulting_revision_id=after.revision_id,
                        post_state_sha256=evidence_hash(target_state(after, cause.target)),
                    )
                )
            continue
        for index, item in enumerate(accepted):
            if item.target != cause.target:
                continue
            state = target_state(after, cause.target)
            if not isinstance(state, KnownValue):
                continue
            predicate = cause.resolution_predicate
            if predicate.kind == "gap_satisfied":
                if _gap_state(state) != "satisfied":
                    continue
                disposition = "resolved"
            elif predicate.kind == "material_choice":
                if method == "selected_offered_value" and (
                    question is None or question.cause_id != cause.cause_id
                ):
                    continue
                disposition = (
                    "resolved"
                    if item.accepted_dictionary_value in predicate.offered_values
                    else "superseded"
                )
                if disposition == "superseded" and method != "accepted_correction":
                    continue
            elif predicate.kind == "offer_decided":
                # A correction is not implicit acceptance/cancellation of a recommendation.
                if question is None or question.cause_id != cause.cause_id:
                    continue
                disposition = "resolved"
            else:
                continue
            assertions.append(
                ResolutionAssertion(
                    cause_id=cause.cause_id,
                    target=cause.target,
                    source_message_id=item.source_message_id,
                    accepted_target_evidence_index=index,
                    method="same_value_explicit_resolution"
                    if item.transition == "NO_CHANGE"
                    else method,
                    disposition=disposition,
                    reason_code="canonical_target_satisfies_exact_predicate",
                    resulting_revision_id=after.revision_id,
                    post_state_sha256=item.after_state_sha256,
                )
            )
    return tuple(assertions)


def advance_frontier(plan, result, *, record_id, result_kind):
    """Project one validated event, preserving every unaffected cause byte-for-byte."""
    states = {s.cause_id: s for s in plan.frontier_core.cause_states}
    if result_kind == "clarification":
        question = next(
            (q for q in plan.questions if q.clarification_id == result.clarification_id), None
        )
        if question is None:
            raise ValueError("Answer does not match the source plan")
        old = states[question.cause_id]
        updates = {
            "last_answer_ref": AnswerReference(
                record_id=record_id,
                content_hash=result.content_hash,
                decision=result.decision.value,
                outcome=result.outcome.value,
            )
        }
        if result.decision in {"SKIP", "UNKNOWN"} or result.outcome == "DEFERRED":
            updates["offer_state"] = "DORMANT"
        states[question.cause_id] = old.model_copy(update=updates)
    for index, assertion in enumerate(result.resolution_assertions):
        if assertion.cause_id not in states or states[assertion.cause_id].status != "OPEN":
            raise ValueError("Resolution does not refer to an OPEN source cause")
        old = states[assertion.cause_id]
        states[assertion.cause_id] = old.model_copy(
            update=dict(
                status={"resolved": "RESOLVED", "superseded": "SUPERSEDED", "rejected": "REJECTED"}[
                    assertion.disposition
                ],
                offer_state="NONE",
                resolution_ref=ResolutionReference(
                    result_kind=result_kind,
                    record_id=record_id,
                    content_hash=result.content_hash,
                    assertion_index=index,
                ),
            )
        )
    return tuple(states[k] for k in sorted(states))


def validate_accepted_evidence(repository, session_id, organization_id, result):
    """CP1/3/4/5/6: actual retained canonical snapshots, not detached DTO claims."""
    if result.scope.session_id != session_id or result.scope.organization_id != organization_id:
        raise ValueError("Accepted result scope mismatch")
    for item in result.accepted_target_evidence:
        before = repository.get_revision(session_id, item.before_revision_id, organization_id)
        after = repository.get_revision(session_id, item.after_revision_id, organization_id)
        message = repository.get_message(session_id, item.source_message_id, organization_id)
        if (
            message.actor != "user"
            or before.design_id != result.scope.design_id
            or after.design_id != before.design_id
        ):
            raise ValueError("Accepted canonical source scope mismatch")
        if (
            evidence_hash(target_state(before, item.target)) != item.before_state_sha256
            or evidence_hash(target_state(after, item.target)) != item.after_state_sha256
            or item.before_revision_id != result.previous_revision_id
            or item.after_revision_id != (result.new_revision_id or result.previous_revision_id)
            or item.transition != ("APPLIED" if result.new_revision_id else "NO_CHANGE")
        ):
            raise ValueError("Accepted canonical transition evidence mismatch")
        state = target_state(after, item.target)
        if not isinstance(state, KnownValue) or item.accepted_dictionary_value != (
            state.value if isinstance(state.value, str) else None
        ):
            raise ValueError("Accepted value does not match canonical state")
    if result.resolution_assertions and result.outcome not in {"APPLIED", "NO_CHANGE", "REJECTED"}:
        raise ValueError("Unaccepted result cannot discharge a cause")


def correction_accepted_targets(evaluation, before, after, *, scope, source_message_id, outcome):
    """Actual ParserProposal updates or source-verified same-value statements only."""
    if outcome not in {"APPLIED", "NO_CHANGE"}:
        return ()
    targets = {u.concrete_target for u in evaluation.parser_proposal.accepted_updates}
    for disposition in evaluation.dispositions:
        c = disposition.candidate
        if (
            disposition.reason == "already_current"
            and c.classification == "requirement"
            and c.certainty == "explicit"
            and c.normalization_source == "domain_dictionary"
            and c.subject in {"product_body", "center_stone"}
        ):
            targets.add(c.target.value)
    result = []
    for concrete in sorted(targets):
        try:
            target = canonical_target(after, concrete, scope=scope)
            state = target_state(after, target)
        except ValueError:
            continue
        if not isinstance(state, KnownValue):
            continue
        candidates = tuple(
            d.candidate
            for d in evaluation.dispositions
            if d.candidate.target is not None
            and d.candidate.target.value == concrete
            and d.candidate.classification == "requirement"
            and d.candidate.certainty == "explicit"
            and d.candidate.subject in {"product_body", "center_stone"}
        )
        result.append(
            accepted_target(
                before,
                after,
                concrete,
                scope=scope,
                source_message_id=source_message_id,
                candidate_ids=tuple(c.candidate_id for c in candidates),
                normalization_refs=tuple(
                    sorted({v for c in candidates for v in c.normalized_values})
                ),
            )
        )
    return tuple(result)


DEPENDENCIES = {
    "METAL_MATERIAL": ("metal.material",),
    "METAL_COLOR": ("metal.color",),
    "CENTER_STONE_SHAPE": ("center_stone.shape",),
    "CENTER_STONE_SETTING": ("center_stone.setting",),
    "CENTER_STONE_DIMENSIONS": (
        "center_stone.dimensions",
        "center_stone.material",
        "center_stone.shape",
        "center_stone.weight",
    ),
}


def context_fingerprint(cause, question, revision):
    from jewelai_domain.lock_protection import state_fields

    dependencies = (
        (cause.target.concrete_target,)
        if question.semantic_question_id == "SIDE_STONE_QUANTITY"
        else DEPENDENCIES[question.semantic_question_id]
    )
    fields = state_fields(revision.design)
    return evidence_hash(
        dict(
            question_id=question.semantic_question_id,
            target=cause.target,
            dependency_canonical_state_hashes={
                d: evidence_hash(fields.get(tuple(d.split(".")))) for d in dependencies
            },
            offered_dictionary_ids=tuple(o.value for o in question.options),
            release_pin=cause.release_pin,
            artifact_pins=cause.artifact_pins,
        )
    )


def relevant_reoffers(plan, result, before, after, *, record_id, projected_states, offer_history):
    states = {s.cause_id: s for s in projected_states}
    accepted = {a.target.concrete_target for a in result.accepted_target_evidence}
    result_refs = {}
    for cause in plan.cause_definitions:
        state = states[cause.cause_id]
        if state.status != "OPEN" or state.offer_state != "DORMANT":
            continue
        question = max(
            (q for q in offer_history if q.cause_id == cause.cause_id),
            key=lambda q: q.offer_ordinal,
            default=None,
        )
        if question is None:
            continue
        dependencies = (
            (cause.target.concrete_target,)
            if question.semantic_question_id == "SIDE_STONE_QUANTITY"
            else DEPENDENCIES[question.semantic_question_id]
        )
        if not accepted.intersection(dependencies):
            continue
        old = context_fingerprint(cause, question, before)
        new = context_fingerprint(cause, question, after)
        if old != new:
            result_refs[cause.cause_id] = RelevantChangeReference(
                accepted_result_record_id=record_id,
                accepted_result_hash=result.content_hash,
                old_context_fingerprint=old,
                new_context_fingerprint=new,
            )
    return result_refs
