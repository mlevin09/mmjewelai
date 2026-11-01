"""F05 correction preparation over the existing deterministic parser/Matrix.

The caller must supply one authenticated, locked, replay-verified frame and must
persist the returned evidence atomically with its actual Plan3. This function
never treats Matrix APPLIED as a committed fact or interprets text as KEEP consent.
"""

import hashlib
from datetime import UTC

from jewelai_domain.clarification_state import evidence_hash
from jewelai_domain.lock_protection import first_locked_change, state_fields
from jewelai_domain.models import Explicit, MessageSource
from jewelai_domain.preservation import (
    RELEASE_TARGETS,
    PendingPreservationRequest,
    ProtectionProjection,
    contract_hash,
    target_state,
)
from jewelai_domain.preservation_release import (
    KeepReleaseIntent,
    project_unprotected_transition,
    requested_value_hash,
)
from jewelai_domain.revisions import revise_design
from jewelai_parser import CandidateCertainty, CandidateClassification
from jewelai_prompts.continuation import continuation_cycle

from .continuation_evaluation import canonical_native_result, evaluate_continuation_message
from .continuation_results import ContinuationCorrectionResult, correction_semantic_hash
from .correction_enrichment import _nonmutating_outcome
from .f04_frontier import correction_accepted_targets, resolving_assertions
from .f04_planning import canonical_target, input_context
from .parsed_enrichment import proposed_design_for_transition


def prepare_correction(
    service,
    repo,
    native,
    plan,
    request,
    *,
    record_id,
    cycle_id,
    plan_id,
    created_at,
    committed_revision=None,
):
    """Recompute actual source/proposal/transition evidence, including during replay."""
    from .continuation_runtime import message_source, request_hash

    sid, oid = plan.context.scope.session_id, plan.context.scope.organization_id
    message, sha = message_source(repo, sid, oid, request.message_id)
    if len(message.content) > 2000:
        from .continuation_preview import ContinuationReadError

        raise ContinuationReadError(
            422, "artifact_capacity_exceeded", "Correction exceeds capacity"
        )
    before, protection = native.snapshot.revision, plan.protection_projection
    if (
        native.frame != request.expected_head
        or protection.current_revision_id != before.revision_id
    ):
        raise ValueError("Correction does not follow its actual verified frame")
    timestamp = message.created_at
    source = MessageSource(
        message_id=str(message.message_id),
        recorded_at=timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp,
    )
    verified = repo.restore_pinned_knowledge_runtime(
        sid,
        oid,
        service.artifact_store,
        active_release=service.active_release,
        validation_report=service.validation_report,
    )
    bound = service._for_session(sid, oid, repository=repo)
    context = plan.context
    native_context = (
        input_context(
            context.scope,
            before,
            cycle_id,
            native.frame.enrichment_cycle_number + 1,
            bound.artifacts,
            verified,
        )
        if context.retained_base == "F"
        else None
    )

    def evaluate(revision):
        return evaluate_continuation_message(
            bound,
            revision,
            message,
            source,
            context=context,
            verified_release=verified,
            role_id=native.session.role_id,
            locale=native.session.locale,
            native_context=native_context,
        )

    first = evaluate(before)
    proposed = proposed_design_for_transition(before, first)
    old_fields, new_fields = state_fields(before.design), state_fields(proposed)
    changes = tuple(
        sorted(
            ".".join(p)
            for p in old_fields.keys() | new_fields.keys()
            if old_fields.get(p) != new_fields.get(p)
        )
    )
    protected = {a.target.concrete_target for a in protection.anchors}
    overlap = tuple(t for t in changes if t in protected)
    authoritative = before
    intents = ()
    if first.parser_proposal.issues:
        outcome, reason = "REJECTED", "parser_rejected"
    elif first_locked_change(old_fields, new_fields) is not None:
        outcome, reason = "REJECTED", "parser_rejected"
    elif overlap and len(changes) > 1:
        outcome, reason = "DEFERRED", "multiple_delta_release_unsupported"
    elif overlap:
        target = overlap[0]
        requested = target_state(proposed, target)
        candidates = tuple(
            d.candidate
            for d in first.dispositions
            if d.concrete_target == target
            and d.candidate.classification == CandidateClassification.REQUIREMENT
            and d.candidate.certainty == CandidateCertainty.EXPLICIT
        )
        if target not in RELEASE_TARGETS or not isinstance(requested, Explicit) or not candidates:
            outcome, reason = "DEFERRED", "unsupported_target"
        else:
            roots = tuple(
                r.root_ref
                for r in sorted(protection.roots, key=lambda r: r.root_ref.evidence_id)
                if any(t.concrete_target == target for t in r.scope_targets)
            )
            spans = []
            for candidate in candidates:
                span = candidate.evidence
                if message.content[span.start : span.end] != span.text:
                    raise ValueError("Correction candidate is not an actual source span")
                spans.append(
                    dict(
                        start=span.start,
                        end=span.end,
                        text_sha256=hashlib.sha256(span.text.encode("utf-8")).hexdigest(),
                    )
                )
            p = dict(
                schema_version="1.0.0",
                context=context,
                origin_head=native.frame,
                correction_record_id=record_id,
                source=source,
                message_sha256=sha,
                parse_version="1.2.0",
                parse_hash=evidence_hash(first.parse_result),
                proposal_hash=evidence_hash(first.parser_proposal),
                source_candidate_ids=tuple(sorted(c.candidate_id for c in candidates)),
                source_spans=tuple(spans),
                target=canonical_target(before, target, scope=context.scope),
                original_before_state=(
                    target_state(before.design, target).model_dump(mode="json")
                    if target_state(before.design, target) is not None
                    else None
                ),
                requested_state=requested.model_dump(mode="json"),
                requested_value_sha256=requested_value_hash(requested.value),
                keep_roots=roots,
            )
            p["intent_id"] = contract_hash("jewelai.KeepReleaseIntent/1.0.0", p)
            intent = KeepReleaseIntent(
                **p, content_hash=contract_hash("jewelai.KeepReleaseIntent/1.0.0", p)
            )
            intents = (intent,)
            outcome, reason = "AWAITING_KEEP_RELEASE", "keep_release_required"
    elif changes:
        authoritative = revise_design(
            before,
            proposed,
            expected_revision_id=before.revision_id,
            source=source,
            reason="Applied an explicitly sourced F05 correction",
            created_at=created_at,
        )
        if committed_revision is not None:
            if authoritative.model_dump(exclude={"revision_id"}) != committed_revision.model_dump(
                exclude={"revision_id"}
            ):
                raise ValueError("Correction replay differs from its actual committed revision")
            authoritative = committed_revision
        outcome, reason = "APPLIED", "supported_changes_applied"
    else:
        outcome, reason = _nonmutating_outcome(first)
    if committed_revision is not None and authoritative != committed_revision:
        raise ValueError("Non-applying correction changed canonical history")
    carried = project_unprotected_transition(
        before=before, after=authoritative, protection=protection
    )
    p = carried.model_dump(mode="json", exclude={"content_hash"})
    from .continuation_planning import release_offer

    offers = tuple(
        release_offer(
            i,
            carried,
            authoritative,
            previous_head=native.frame,
            plan_id=plan_id,
            dictionary=bound.artifacts.dictionary,
            locale=native.session.locale,
        )
        for i in intents
    )
    by_intent = {offer.intent_id: offer for offer in offers}
    p["pending_requests"] = (
        *carried.pending_requests,
        *(
            PendingPreservationRequest(
                intent_id=i.intent_id,
                current_offer_ref=dict(
                    id=by_intent[i.intent_id].offer_id, hash=by_intent[i.intent_id].content_hash
                ),
                status="PENDING",
            )
            for i in intents
        ),
    )
    carried = ProtectionProjection(
        **p, content_hash=contract_hash("jewelai.ProtectionProjection/1.0.0", p)
    )
    post = first if authoritative == before else evaluate(authoritative)
    from .continuation_protection import correction_constraints, extend_protection

    constraints = correction_constraints(plan, post, source, authoritative, cycle_id, repo)
    carried = extend_protection(
        carried, authoritative, constraints, cycle_id, source_text=message.content
    )
    enriched = continuation_cycle(
        context,
        canonical_native_result(bound, authoritative, context, native_context=native_context),
        carried,
    )
    accepted, assertions = (), ()
    if context.retained_base == "F":
        accepted = correction_accepted_targets(
            first,
            before,
            authoritative,
            scope=context.scope,
            source_message_id=message.message_id,
            outcome=outcome,
        )
        # The caller supplies a native view of the ACTUAL Plan3 core/questions.
        from .continuation_planning import native_plan_view

        assertions = resolving_assertions(
            native_plan_view(plan), accepted, authoritative, method="accepted_correction"
        )
    p = dict(
        correction_version="3.0.0",
        context=context,
        request=request,
        request_id=request.request_id,
        request_hash=request_hash("CorrectionRequest", context, request, sha),
        session_id=sid,
        source=source,
        source_message_sha256=sha,
        source_parse=first.parse_result,
        native_proposal=first.parser_proposal,
        correction_evaluation=first,
        post_transition_evaluation=post,
        previous_head=native.frame,
        previous_revision_id=before.revision_id,
        new_revision_id=authoritative.revision_id if authoritative != before else None,
        authoritative_revision=authoritative,
        previous_enrichment_cycle_id=native.frame.enrichment_cycle_id,
        next_enrichment_cycle_id=cycle_id,
        next_enrichment_cycle_number=native.frame.enrichment_cycle_number + 1,
        knowledge_package_id=context.release_pin.package_id,
        knowledge_artifact_version=context.release_pin.artifact_version,
        knowledge_runtime_sha256=context.release_pin.runtime_sha256,
        knowledge_validation_report_sha256=context.release_pin.validation_report_sha256,
        dictionary_artifact_version=context.artifact_pins.dictionary_artifact_version,
        prompt_template_artifact_version=context.artifact_pins.prompt_template_artifact_version,
        outcome=outcome,
        reason=reason,
        keep_intents=intents,
        accepted_target_evidence=accepted,
        resolution_assertions=assertions,
        next_enrichment_result=enriched,
    )
    p["semantic_hash"] = correction_semantic_hash(p)
    result = ContinuationCorrectionResult(
        **p, content_hash=contract_hash("jewelai.CorrectionResult/3.0.0", p)
    )
    return result, offers
