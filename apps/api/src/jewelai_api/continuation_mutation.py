"""One-event F05 plan assembly and verified current-view materialization."""

from copy import copy
from dataclasses import replace

from jewelai_domain.continuation import ContinuationFrameCore
from jewelai_domain.preservation import contract_hash

from .compatibility_projection import project_legacy_readiness
from .continuation_plan import ContinuationPlan
from .continuation_planning import correction_native_plan, native_plan_view
from .continuation_preview import KeepOfferQuestion, NativePreviewQuestion
from .prompt_enrichment_runtime import _decision_lineage


def correction_plan(
    service,
    repo,
    native,
    previous,
    result,
    offers,
    *,
    record_id,
    plan_id,
    verified_extras=(),
    verified_answers=(),
    offer_history=(),
):
    context = previous.context
    sid, oid = context.scope.session_id, context.scope.organization_id
    bound = copy(service._for_session(sid, oid, repository=repo))
    bound.repository = repo
    from .continuation_protection import correction_constraints

    constraints = correction_constraints(
        previous,
        result.post_transition_evaluation,
        result.source,
        result.authoritative_revision,
        result.next_enrichment_cycle_id,
        repo,
    )
    base, unasked = correction_native_plan(
        bound,
        previous,
        result,
        plan_id=plan_id,
        record_id=record_id,
        constraints=constraints,
        offer_history=offer_history or previous.native_base.native_questions,
    )
    if context.retained_base == "L":
        # Native blockers remain visible. KEEP pending is represented separately
        # by the exact logical requests, never by rewriting a native question.
        old_audit = tuple(
            d.model_copy(
                update={"applies_to_revision_id": result.authoritative_revision.revision_id}
            )
            for d in native.snapshot.decision_lineage
        )
        added = _decision_lineage(
            sid,
            result.authoritative_revision.revision_id,
            (),
            (result,),
            {result.content_hash: result.outcome == "DEFERRED"},
        )
        base = base.model_copy(
            update={
                "native_decision_audit": tuple(
                    sorted(
                        (*old_audit, *added), key=lambda d: (d.kind, d.decision_id, d.content_hash)
                    )
                )
            }
        )
    core = ContinuationFrameCore(
        revision_id=result.authoritative_revision.revision_id,
        revision_sha256=result.next_enrichment_result.protection_projection.current_revision_sha256,
        enrichment_cycle_id=result.next_enrichment_cycle_id,
        enrichment_cycle_number=result.next_enrichment_cycle_number,
        enrichment_result_hash=result.next_enrichment_result.content_hash,
        plan_id=plan_id,
    )
    compat = None
    if context.retained_base == "L":
        evidence_view = replace(
            native,
            snapshot=native.snapshot.model_copy(
                update={
                    "revision": result.authoritative_revision,
                    "decision_lineage": base.native_decision_audit,
                }
            ),
            protection=result.next_enrichment_result.protection_projection,
        )
        source = project_legacy_readiness(
            bound,
            repo,
            evidence_view,
            sid,
            oid,
            _verified_extra=verified_extras,
            _verified_answers=verified_answers,
            _legacy_root=previous.compatibility_projection.legacy_history_root_sha256,
        )
        p = source.model_dump(mode="json", exclude={"content_hash"})
        p.update(build_mode="embedded_plan", current_frame_core=core, evidence_head=native.frame)
        compat = type(source)(
            **p, content_hash=contract_hash("jewelai.CompatibilityReadinessProjection/1.0.0", p)
        )
    p = dict(
        plan_version="3.0.0",
        context=context,
        allocated_current_frame_core=core,
        previous_head=native.frame,
        design_revision_id=str(core.revision_id),
        knowledge_package_id=context.release_pin.package_id,
        knowledge_artifact_version=context.release_pin.artifact_version,
        knowledge_runtime_sha256=context.release_pin.runtime_sha256,
        knowledge_validation_report_sha256=context.release_pin.validation_report_sha256,
        dictionary_artifact_version=previous.dictionary_artifact_version,
        question_artifact_version=previous.question_artifact_version,
        rules_artifact_version=previous.rules_artifact_version,
        locale=previous.locale,
        role_id=previous.role_id,
        native_base=base,
        historical_base_plan_ref=previous.historical_base_plan_ref,
        questions=tuple(
            NativePreviewQuestion(
                question_kind="NATIVE", retained_base=context.retained_base, native_question=q
            )
            for q in base.native_questions
        )
        + tuple(KeepOfferQuestion(question_kind="KEEP_RELEASE", offer=o) for o in offers),
        unasked_evidence=unasked,
        constraint_evidence=constraints,
        protection_projection=result.next_enrichment_result.protection_projection,
        compatibility_projection=compat,
        trigger=dict(
            trigger_kind="CORRECTION",
            record_id=record_id,
            result_hash=result.content_hash,
            request_hash=result.request_hash,
            message_id=result.request.message_id,
            message_sha256=result.source_message_sha256,
            previous_head=native.frame,
        ),
    )
    return ContinuationPlan(**p, content_hash=contract_hash("jewelai.ClarificationPlan/3.0.0", p))


def current_view(
    service, repo, origin, verified, prefix, *, extra_corrections=(), extra_answers=()
):
    """Materialize only an already source-replayed interval, never unverified rows."""
    from .clarification_v2 import ClarificationPlanV2, seal_frontier

    cycle, plan, frame = verified[-1]
    sid, oid = plan.context.scope.session_id, plan.context.scope.organization_id
    revision = repo.get_revision(sid, frame.revision_id, oid)
    if plan.context.retained_base == "L":
        audit = plan.native_base.native_decision_audit
    else:
        audit = tuple(
            d.model_copy(update={"applies_to_revision_id": revision.revision_id})
            for d in origin.snapshot.decision_lineage
        )
        audit += _decision_lineage(
            sid,
            revision.revision_id,
            (),
            tuple(r for _, r, _, _ in extra_corrections),
            {r.content_hash: r.outcome == "DEFERRED" for _, r, _, _ in extra_corrections},
        )
        audit += tuple(answer_audit(r, revision.revision_id) for _, r, _, _ in extra_answers)
        audit = tuple(sorted(audit, key=lambda d: (d.kind, d.decision_id, d.content_hash)))
    snapshot = origin.snapshot.model_copy(
        update=dict(
            revision=revision,
            enrichment_cycle_id=cycle.enrichment_cycle_id,
            latest_enrichment_cycle_id=cycle.enrichment_cycle_id,
            enrichment_cycle_number=cycle.cycle_number,
            enrichment_result=cycle.result,
            rule_decision=plan.native_base.rule_decision,
            constraint_evidence=plan.constraint_evidence,
            decision_lineage=audit,
            artifact_versions=origin.snapshot.artifact_versions.model_copy(
                update={"enrichment_version": "3.0.0"}
            ),
        )
    )
    from .continuation_history import _native_roots

    current = replace(
        origin,
        roots=_native_roots(repo, sid, oid, native_plan_view(plan)),
        frame=frame,
        snapshot=snapshot,
        plan=native_plan_view(plan),
        protection=plan.protection_projection,
    )
    compat = None
    if plan.context.retained_base == "L":
        compat = project_legacy_readiness(
            service,
            repo,
            current,
            sid,
            oid,
            _verified_extra=extra_corrections,
            _verified_answers=extra_answers,
            _legacy_root=origin.frame.history_root_sha256,
        )
        p = compat.model_dump(mode="json", exclude={"content_hash"})
        p.update(evidence_head=frame, current_frame_core=plan.allocated_current_frame_core)
        compat = type(compat)(
            **p, content_hash=contract_hash("jewelai.CompatibilityReadinessProjection/1.0.0", p)
        )
    else:
        old = [
            ClarificationPlanV2.model_validate(p.plan_payload)
            for p in prefix.list_clarification_plans(sid, oid)
        ]
        new = [native_plan_view(p) for _, p, _ in verified]
        snapshot = snapshot.model_copy(
            update={
                "cause_definitions": plan.native_base.cause_definitions,
                "effective_unresolved_frontier": seal_frontier(
                    native_plan_view(plan), (*old, *new)
                ),
            }
        )
        current = replace(current, snapshot=snapshot)
    return current, plan, compat


def answer_audit(result, revision_id):
    from jewelai_domain.preservation import target_state
    from jewelai_prompts.final_prompt import FinalPromptDecisionLineage

    target = None
    value = None
    blocks = False
    if result.answer_kind == "NATIVE":
        native = result.native_result
        target = (
            native.target.concrete_target
            if hasattr(native.target, "concrete_target")
            else native.target
        )
        value = native.selected_option.value if native.selected_option is not None else None
        blocks = native.blocks_progression
    elif result.keep_decision.accepted_target is not None:
        target = result.keep_decision.accepted_target.target.concrete_target
        value = target_state(result.resulting_revision.design, target).model_dump(mode="json")[
            "value"
        ]
    return FinalPromptDecisionLineage(
        kind="clarification",
        session_id=result.session_id,
        decision_id=result.clarification_id,
        decision=result.decision.value,
        outcome=result.outcome.value,
        target=target,
        selected_value=value,
        source_revision_id=result.previous_revision_id,
        resulting_revision_id=result.new_revision_id,
        applies_to_revision_id=revision_id,
        knowledge_package_id=result.knowledge_package_id,
        knowledge_artifact_version=result.knowledge_artifact_version,
        knowledge_runtime_sha256=result.knowledge_runtime_sha256,
        knowledge_validation_report_sha256=result.knowledge_validation_report_sha256,
        question_artifact_version=result.question_artifact_version,
        rules_artifact_version=result.rules_artifact_version,
        blocks_progression=blocks,
        content_hash=result.content_hash,
    )


def answer_plan(
    service,
    repo,
    native,
    previous,
    result,
    *,
    cycle_id,
    plan_id,
    verified_extras=(),
    verified_answers=(),
    offer_history=(),
):
    from types import SimpleNamespace

    from .continuation_planning import answer_native_plan

    context = previous.context
    sid, oid = context.scope.session_id, context.scope.organization_id
    bound = copy(service._for_session(sid, oid, repository=repo))
    verified_answers = (
        *verified_answers,
        (
            SimpleNamespace(answer_record_id=result.answer_id, content_hash=result.content_hash),
            result,
            native.snapshot.revision,
            result.resulting_revision or native.snapshot.revision,
        ),
    )
    bound.repository = repo
    revision = result.resulting_revision or native.snapshot.revision
    base, unasked = answer_native_plan(
        bound,
        previous,
        result,
        revision,
        plan_id=plan_id,
        cycle_id=cycle_id,
        offer_history=offer_history,
    )
    if context.retained_base == "L":
        audit = tuple(
            d.model_copy(update={"applies_to_revision_id": revision.revision_id})
            for d in native.snapshot.decision_lineage
        ) + (answer_audit(result, revision.revision_id),)
        base = base.model_copy(
            update={
                "native_decision_audit": tuple(
                    sorted(audit, key=lambda d: (d.kind, d.decision_id, d.content_hash))
                )
            }
        )
    core = ContinuationFrameCore(
        revision_id=revision.revision_id,
        revision_sha256=result.next_enrichment_result.protection_projection.current_revision_sha256,
        enrichment_cycle_id=cycle_id,
        enrichment_cycle_number=native.frame.enrichment_cycle_number + 1,
        enrichment_result_hash=result.next_enrichment_result.content_hash,
        plan_id=plan_id,
    )
    compat = None
    if context.retained_base == "L":
        view = replace(
            native,
            snapshot=native.snapshot.model_copy(
                update={"revision": revision, "decision_lineage": base.native_decision_audit}
            ),
            protection=result.next_enrichment_result.protection_projection,
        )
        source = project_legacy_readiness(
            bound,
            repo,
            view,
            sid,
            oid,
            _verified_extra=verified_extras,
            _verified_answers=verified_answers,
            _legacy_root=previous.compatibility_projection.legacy_history_root_sha256,
        )
        p = source.model_dump(mode="json", exclude={"content_hash"})
        p.update(build_mode="embedded_plan", current_frame_core=core, evidence_head=native.frame)
        compat = type(source)(
            **p, content_hash=contract_hash("jewelai.CompatibilityReadinessProjection/1.0.0", p)
        )
    p = previous.model_dump(mode="python", exclude={"content_hash"})
    p.update(
        allocated_current_frame_core=core,
        previous_head=native.frame,
        design_revision_id=str(revision.revision_id),
        native_base=base,
        questions=tuple(
            NativePreviewQuestion(
                question_kind="NATIVE", retained_base=context.retained_base, native_question=q
            )
            for q in base.native_questions
        ),
        unasked_evidence=unasked,
        protection_projection=result.next_enrichment_result.protection_projection,
        compatibility_projection=compat,
        trigger=dict(
            trigger_kind="ANSWER",
            record_id=result.answer_id,
            result_hash=result.content_hash,
            request_hash=result.request_hash,
            message_id=result.request.message_id,
            message_sha256=result.message_sha256,
            previous_head=native.frame,
        ),
    )
    return ContinuationPlan(**p, content_hash=contract_hash("jewelai.ClarificationPlan/3.0.0", p))
