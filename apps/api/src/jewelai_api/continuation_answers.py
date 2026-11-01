"""Typed F05 consent and native-answer preparation; no text-implied authority."""

from copy import copy
from datetime import UTC
from types import SimpleNamespace

from jewelai_domain.dictionary import DictionaryCategory
from jewelai_domain.lock_protection import locked_ancestor, state_fields
from jewelai_domain.models import KnownValue, MessageSource
from jewelai_domain.preservation import (
    anchor_hash,
    contract_hash,
    target_state,
)
from jewelai_domain.preservation_release import (
    KeepReleaseDecision,
    project_unprotected_transition,
    project_verified_release,
    requested_value_hash,
)
from jewelai_domain.revisions import RevisionConflict, revise_design
from jewelai_parser import ParserTarget
from jewelai_prompts.continuation import continuation_cycle

from .clarification_answers import ClarificationAnswerError, _parser_proposal, _resolve_decision
from .clarification_f05 import KeepReleaseAnswerRequest
from .continuation_planning import native_plan_view
from .continuation_preview import ContinuationReadError
from .continuation_results import KeepAnswerResultV3, NativeAnswerResultV3
from .f04_frontier import accepted_target, correction_accepted_targets, resolving_assertions
from .f04_planning import input_context


def _source(message):
    at = message.created_at
    return MessageSource(
        message_id=str(message.message_id),
        recorded_at=at.replace(tzinfo=UTC) if at.tzinfo is None else at,
    )


def _child(before, after, actual):
    if actual is not None:
        if after.model_dump(exclude={"revision_id"}) != actual.model_dump(exclude={"revision_id"}):
            raise ValueError("Answer3 replay has another canonical transition")
        return actual
    return after


def _next_native(service, repo, native, plan, after, *, cycle_id):
    if after == native.snapshot.revision:
        return native.snapshot.enrichment_result.native
    bound = copy(
        service._for_session(
            plan.context.scope.session_id, plan.context.scope.organization_id, repository=repo
        )
    )
    bound.repository = repo
    from .continuation_evaluation import canonical_native_result

    source_context = (
        input_context(
            plan.context.scope,
            native.snapshot.revision,
            cycle_id,
            native.frame.enrichment_cycle_number + 1,
            bound.artifacts,
            plan.context.release_pin,
        )
        if plan.context.retained_base == "F"
        else None
    )
    return canonical_native_result(bound, after, plan.context, native_context=source_context)


def prepare_answer(
    service, repo, native, plan, request, *, cycle_id, created_at, intents, committed_revision=None
):
    from .continuation_runtime import message_source, request_hash

    sid, oid = plan.context.scope.session_id, plan.context.scope.organization_id
    message, sha = message_source(repo, sid, oid, request.message_id)
    source = _source(message)
    if (
        request.expected_head != native.frame
        or request.clarification_plan_id != native.frame.plan_id
    ):
        raise ValueError("Answer3 does not follow its verified current frame")
    context = plan.context
    before = native.snapshot.revision
    bound = copy(service._for_session(sid, oid, repository=repo))
    bound.repository = repo
    wire_hash = request_hash("AnswerRequest", context, request, sha)
    after = before
    accepted = ()
    assertions = ()
    payload_native = None
    decision_evidence = None
    if isinstance(request, KeepReleaseAnswerRequest):
        question = next(
            (
                q
                for q in plan.questions
                if q.question_kind == "KEEP_RELEASE"
                and q.offer.offer_id == request.clarification_id
            ),
            None,
        )
        if question is None:
            raise ContinuationReadError(
                409, "stale_clarification_plan", "Scoped confirmation offer is not current"
            )
        offer = question.offer
        entry = intents.get(request.intent_id)
        if entry is None:
            raise ValueError("Current scoped offer has no original verified correction")
        intent, correction = entry
        if (
            offer.intent_id != request.intent_id
            or offer.requested_value_sha256 != request.requested_value_sha256
            or intent.requested_value_sha256 != request.requested_value_sha256
        ):
            raise ContinuationReadError(
                409, "clarification_conflict", "Scoped confirmation does not match its actual offer"
            )
        if request.decision == "ACCEPT":
            current = target_state(before.design, intent.target.concrete_target)
            if (
                isinstance(current, KnownValue)
                and requested_value_hash(current.value) == intent.requested_value_sha256
            ):
                raise ContinuationReadError(
                    409,
                    "intent_no_longer_applicable",
                    "Requested value is already current; explicit closure is required",
                )
            if request.decision not in offer.allowed_decisions:
                raise ContinuationReadError(
                    409, "clarification_conflict", "Scoped action is not offered"
                )
            proposed = before.design.model_dump(mode="python")
            field = intent.target.concrete_target.split(".")[1]
            proposed["center_stone"][field] = intent.requested_state.model_dump(mode="python")
            try:
                generated = revise_design(
                    before,
                    proposed,
                    expected_revision_id=before.revision_id,
                    source=source,
                    reason="Applied an explicitly authorized scoped KEEP release",
                    created_at=created_at,
                )
            except RevisionConflict:
                raise ContinuationReadError(
                    409, "clarification_conflict", "Canonical LOCK prevents this scoped change"
                ) from None
            after = _child(before, generated, committed_revision)
            outcome, reason = "APPLIED", "keep_release_authorized"
            released = dict(
                target=intent.target,
                before_state_sha256=anchor_hash(current),
                after_state_sha256=anchor_hash(
                    target_state(after.design, intent.target.concrete_target)
                ),
            )
        else:
            outcome, reason = "REJECTED", "keep_release_rejected"
            released = None
        p = dict(
            schema_version="1.0.0",
            decision_id=request.answer_id,
            request_hash=wire_hash,
            context=context,
            intent_id=intent.intent_id,
            offer_id=offer.offer_id,
            binding_hash=offer.binding.content_hash,
            previous_head=native.frame,
            decision=request.decision,
            source=source,
            message_sha256=sha,
            outcome=outcome,
            resulting_revision_id=after.revision_id if after != before else None,
            accepted_target=released,
        )
        decision_evidence = KeepReleaseDecision(
            **p, content_hash=contract_hash("jewelai.KeepReleaseDecision/1.0.0", p)
        )
        protection = project_verified_release(
            before=before,
            after=after,
            protection=plan.protection_projection,
            roots=native.roots,
            intent=intent,
            offer=offer,
            decision=decision_evidence,
            current_head=native.frame,
        )
        if context.retained_base == "F" and outcome == "APPLIED":
            accepted = correction_accepted_targets(
                correction.correction_evaluation,
                before,
                after,
                scope=context.scope,
                source_message_id=intent.source.message_id,
                outcome="APPLIED",
            )
            # Only the requested target was committed; other pending batch facts
            # cannot acquire accepted-target authority from this one-field consent.
            accepted = tuple(a for a in accepted if a.target == intent.target)
            assertions = resolving_assertions(
                native_plan_view(plan), accepted, after, method="accepted_correction"
            )
        decision = request.decision
    else:
        if request.native.retained_base != context.retained_base:
            raise ContinuationReadError(
                409,
                "unsupported_workflow_version",
                "Native answer profile differs from retained base",
            )
        wrapper = next(
            (
                q
                for q in plan.questions
                if q.question_kind == "NATIVE"
                and q.native_question.clarification_id == request.clarification_id
            ),
            None,
        )
        if wrapper is None:
            raise ContinuationReadError(
                409, "stale_clarification_plan", "Native question is not currently offered"
            )
        question = wrapper.native_question
        decision = request.native.decision
        if context.retained_base == "F" and decision not in question.allowed_decisions:
            raise ContinuationReadError(
                422, "invalid_clarification_decision", "Native decision is not allowed"
            )
        try:
            option = _resolve_decision(question, request.native)
        except ClarificationAnswerError:
            raise ContinuationReadError(
                422,
                "invalid_clarification_option",
                "Native choice does not match the actual question",
            ) from None
        if (
            context.retained_base == "F"
            and decision == "SELECT_OPTION"
            and option.option_id != request.native.selected_option_id
        ):
            raise ContinuationReadError(
                422, "invalid_clarification_option", "Native option ID/value do not match"
            )
        target = (
            question.target.concrete_target
            if context.retained_base == "F"
            else question.target.value
        )
        fields = state_fields(before.design)
        state = fields.get(tuple(target.split(".")))
        resolved = False
        if decision in {"SELECT_OPTION", "ACCEPT"}:
            same = isinstance(state, KnownValue) and state.value == option.value
            if not same and target in {
                a.target.concrete_target for a in plan.protection_projection.anchors
            }:
                raise ContinuationReadError(
                    409,
                    "clarification_conflict",
                    "A different preserved value requires separate scoped KEEP confirmation",
                )
            if context.retained_base == "F" and same:
                outcome, reason = "NO_CHANGE", "value_already_current"
                resolved = True
            elif (
                bool(getattr(state, "confirmed", False))
                or locked_ancestor(fields, tuple(target.split("."))) is not None
            ):
                outcome, reason = "DEFERRED", "target_protected"
            else:
                try:
                    proposal = _parser_proposal(
                        question,
                        option,
                        SimpleNamespace(source=source),
                        before,
                        bound.artifacts.dictionary,
                        **(
                            {
                                "_target": ParserTarget.METAL_MATERIAL,
                                "_category": DictionaryCategory.METAL_MATERIAL,
                            }
                            if question.semantic_question_id == "METAL_MATERIAL"
                            else {}
                        ),
                    )
                except ClarificationAnswerError:
                    raise ContinuationReadError(
                        422,
                        "invalid_clarification_option",
                        "Offered native value is no longer supported",
                    ) from None
                if proposal is None:
                    outcome, reason = "DEFERRED", "unsupported_application"
                elif proposal.issues:
                    outcome, reason = "DEFERRED", "parser_rejected"
                elif not proposal.has_changes:
                    outcome, reason = "NO_CHANGE", "value_already_current"
                    resolved = True
                else:
                    try:
                        generated = revise_design(
                            before,
                            proposal.proposed_design,
                            expected_revision_id=before.revision_id,
                            source=source,
                            reason="Applied an explicitly authorized clarification answer",
                            created_at=created_at,
                        )
                        after = _child(before, generated, committed_revision)
                        outcome = "APPLIED"
                        resolved = True
                        reason = (
                            "user_selected_offered_option"
                            if decision == "SELECT_OPTION"
                            else "user_accepted_recommendation"
                            if question.category == "knowledge_recommendation"
                            else "user_accepted_preference"
                        )
                    except RevisionConflict:
                        outcome, reason = "DEFERRED", "parser_rejected"
        else:
            outcome, reason = {
                "REJECT": ("REJECTED", "user_rejected_offer"),
                "SKIP": ("SKIPPED", "user_skipped"),
                "UNKNOWN": ("UNKNOWN", "user_does_not_know"),
            }[decision.value]
            resolved = decision == "REJECT"
        protection = project_unprotected_transition(
            before=before, after=after, protection=plan.protection_projection
        )
        blocks = (
            any(
                s.cause_id == question.cause_id and s.blocks_current
                for s in plan.native_base.frontier_core.cause_states
            )
            if context.retained_base == "F"
            else question.importance == "blocking"
        ) and not resolved
        payload_native = dict(
            retained_base=context.retained_base,
            semantic_question_id=question.semantic_question_id,
            target=question.target,
            subject=question.subject,
            selected_option=option,
            source_candidate_ids=question.source_candidate_ids,
            source_proposal_ids=question.source_proposal_ids,
            evidence=question.evidence,
            question_resolved=resolved,
            blocks_progression=blocks,
            knowledge_package_id=plan.knowledge_package_id,
            knowledge_artifact_version=plan.knowledge_artifact_version,
            knowledge_runtime_sha256=plan.knowledge_runtime_sha256,
            knowledge_validation_report_sha256=plan.knowledge_validation_report_sha256,
            question_artifact_version=plan.question_artifact_version,
            rules_artifact_version=plan.rules_artifact_version,
        )
        if context.retained_base == "F":
            payload_native["selected_option_id"] = option.option_id if option else None
            if resolved and decision not in {"SKIP", "UNKNOWN", "REJECT"}:
                accepted = (
                    accepted_target(
                        before,
                        after,
                        target,
                        scope=context.scope,
                        source_message_id=message.message_id,
                        candidate_ids=question.source_candidate_ids,
                        normalization_refs=(option.option_id, option.value),
                    ),
                )
                assertions = resolving_assertions(
                    native_plan_view(plan),
                    accepted,
                    after,
                    method="selected_offered_value",
                    question_id=question.clarification_id,
                )
            elif decision == "REJECT":
                assertions = resolving_assertions(
                    native_plan_view(plan),
                    (),
                    after,
                    method="selected_offered_value",
                    question_id=question.clarification_id,
                    rejected=True,
                    source_message_id=message.message_id,
                )
    if committed_revision is not None and after != committed_revision:
        raise ValueError("Answer3 replay changed a non-applying canonical state")
    enriched = continuation_cycle(
        context, _next_native(bound, repo, native, plan, after, cycle_id=cycle_id), protection
    )
    p = dict(
        answer_version="3.0.0",
        answer_kind=request.answer_kind,
        context=context,
        request=request,
        answer_id=request.answer_id,
        request_hash=wire_hash,
        session_id=sid,
        source=source,
        message_sha256=sha,
        previous_head=native.frame,
        clarification_plan_id=request.clarification_plan_id,
        clarification_id=request.clarification_id,
        plan_content_hash=native.frame.plan_hash,
        decision=decision,
        outcome=outcome,
        reason=reason,
        previous_revision_id=before.revision_id,
        new_revision_id=after.revision_id if after != before else None,
        resulting_revision=after if after != before else None,
        answer_hash=wire_hash,
        knowledge_package_id=plan.knowledge_package_id,
        knowledge_artifact_version=plan.knowledge_artifact_version,
        knowledge_runtime_sha256=plan.knowledge_runtime_sha256,
        knowledge_validation_report_sha256=plan.knowledge_validation_report_sha256,
        question_artifact_version=plan.question_artifact_version,
        rules_artifact_version=plan.rules_artifact_version,
        accepted_target_evidence=accepted,
        resolution_assertions=assertions,
        next_enrichment_result=enriched,
    )
    if payload_native is not None:
        p["native_result"] = payload_native
        cls = NativeAnswerResultV3
    else:
        p["keep_decision"] = decision_evidence
        cls = KeepAnswerResultV3
    return cls(**p, content_hash=contract_hash("jewelai.AnswerResult/3.0.0", p))
