"""Explicit F05 re-offers, source-bound to a verified current frame."""

from jewelai_domain.continuation import ContinuationFrameCore
from jewelai_domain.preservation import contract_hash
from jewelai_domain.preservation_release import project_unprotected_transition
from jewelai_prompts.continuation import continuation_cycle

from .clarification_f05 import KeepReleaseResumeRequest
from .continuation_plan import ContinuationPlan, NativeFPlanEvidence
from .continuation_planning import NativePlanViewReader, native_plan_view, release_offer
from .continuation_preview import ContinuationReadError, KeepOfferQuestion, NativePreviewQuestion


def prepare_resume(service, repo, view, previous, request, *, cycle_id, plan_id, intents, offers):
    from .continuation_runtime import message_source, request_hash

    context = previous.context
    sid, oid = context.scope.session_id, context.scope.organization_id
    _, sha = message_source(repo, sid, oid, request.message_id)
    if request.expected_head != view.frame:
        raise ContinuationReadError(
            409, "stale_clarification_plan", "Current workflow frame changed"
        )
    revision = view.snapshot.revision
    protection = project_unprotected_transition(
        before=revision, after=revision, protection=previous.protection_projection
    )
    native = previous.native_base
    unasked = previous.unasked_evidence
    keep_offers = ()
    if isinstance(request, KeepReleaseResumeRequest):
        pending = next(
            (p for p in protection.pending_requests if p.intent_id == request.intent_id), None
        )
        if pending is None or request.intent_id not in intents:
            raise ContinuationReadError(
                409, "clarification_conflict", "Logical request is not pending"
            )
        intent = intents[request.intent_id][0]
        old_offer = next((o for o in reversed(offers) if o.intent_id == intent.intent_id), None)
        if old_offer is None:
            raise ValueError("Pending intent has no actual historical offer")
        offer = release_offer(
            intent,
            protection,
            revision,
            previous_head=view.frame,
            plan_id=plan_id,
            dictionary=service._for_session(sid, oid, repository=repo).artifacts.dictionary,
            locale=previous.locale,
            previous_offer=old_offer,
        )
        p = protection.model_dump(mode="python", exclude={"content_hash"})
        p["pending_requests"] = tuple(
            type(item).model_validate(
                {
                    **item.model_dump(mode="python"),
                    "status": "PENDING",
                    "current_offer_ref": dict(id=offer.offer_id, hash=offer.content_hash),
                }
            )
            if item.intent_id == intent.intent_id
            else item
            for item in protection.pending_requests
        )
        protection = type(protection)(
            **p, content_hash=contract_hash("jewelai.ProtectionProjection/1.0.0", p)
        )
        keep_offers = (KeepOfferQuestion(question_kind="KEEP_RELEASE", offer=offer),)
    else:
        if context.retained_base != "F":
            raise ContinuationReadError(
                409, "unsupported_workflow_version", "Native resume requires retained F"
            )
        from .clarification_v2 import ResumeTrigger
        from .f04_planning import plan_f04, protected_target

        old = native_plan_view(previous)
        state = next(
            (s for s in native.frontier_core.cause_states if s.cause_id == request.cause_id), None
        )
        definition = next(
            (d for d in native.cause_definitions if d.cause_id == request.cause_id), None
        )
        if (
            state is None
            or definition is None
            or (state.status, state.offer_state) != ("OPEN", "DORMANT")
            or protected_target(revision, definition.target, previous.constraint_evidence)
            or not any(q.cause_id == request.cause_id for q in offers)
        ):
            raise ContinuationReadError(
                409, "clarification_conflict", "Cause is not eligible for explicit resume"
            )

        def finish(**payload):
            return NativeFPlanEvidence(
                retained_base="F",
                rule_decision=payload["rule_decision"],
                native_questions=payload["questions"],
                conflicts=payload["conflicts"],
                cause_definitions=payload["cause_definitions"],
                frontier_core=payload["frontier_core"],
                availability_overlay=view.snapshot.enrichment_result.native.availability_overlay,
            ), payload["unasked_evidence"]

        native, unasked = plan_f04(
            revision,
            view.snapshot.enrichment_result.native,
            artifacts=service._for_session(sid, oid, repository=repo).artifacts,
            role_id=previous.role_id,
            plan_id=plan_id,
            cycle_id=cycle_id,
            cycle_number=view.frame.enrichment_cycle_number + 1,
            # Reuse the existing source-reference type, not a legacy result or
            # request: its hash commits the actual approved ResumeRequest3.
            trigger=ResumeTrigger(
                kind="explicit_resume",
                request_id=request.request_id,
                request_hash=request_hash("ResumeRequest", context, request, sha),
                message_id=request.message_id,
                cause_id=request.cause_id,
                previous_plan_id=view.frame.plan_id,
                previous_plan_hash=view.frame.plan_hash,
            ),
            previous_plan=old,
            current_states=native.frontier_core.cause_states,
            constraint_evidence=previous.constraint_evidence,
            resume_cause_id=request.cause_id,
            offer_history=offers,
            _plan_builder=finish,
            _previous_plan_reader=NativePlanViewReader,
        )
    cycle = continuation_cycle(
        context=context, native=view.snapshot.enrichment_result.native, protection=protection
    )
    core = ContinuationFrameCore(
        revision_id=revision.revision_id,
        revision_sha256=protection.current_revision_sha256,
        enrichment_cycle_id=cycle_id,
        enrichment_cycle_number=view.frame.enrichment_cycle_number + 1,
        enrichment_result_hash=cycle.content_hash,
        plan_id=plan_id,
    )
    compat = previous.compatibility_projection
    if compat is not None:
        p = compat.model_dump(mode="python", exclude={"content_hash"})
        p.update(current_frame_core=core, evidence_head=view.frame)
        compat = type(compat)(
            **p, content_hash=contract_hash("jewelai.CompatibilityReadinessProjection/1.0.0", p)
        )
    p = previous.model_dump(mode="python", exclude={"content_hash"})
    p.update(
        allocated_current_frame_core=core,
        previous_head=view.frame,
        native_base=native,
        questions=(
            *tuple(
                NativePreviewQuestion(
                    question_kind="NATIVE", retained_base=context.retained_base, native_question=q
                )
                for q in native.native_questions
            ),
            *keep_offers,
        ),
        unasked_evidence=unasked,
        protection_projection=protection,
        compatibility_projection=compat,
        trigger=dict(
            trigger_kind="RESUME",
            request=request,
            request_hash=request_hash("ResumeRequest", context, request, sha),
            source_message_sha256=sha,
            previous_head=view.frame,
        ),
    )
    return cycle, ContinuationPlan(
        **p, content_hash=contract_hash("jewelai.ClarificationPlan/3.0.0", p)
    )
