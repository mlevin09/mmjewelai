"""Reuse native L effective-block policy on an already source-replayed3 prefix.

No target/value coincidence creates a resolution. Only the original source
constraints, native noncritical evidence and exact question-bound answer
continuations can discharge a deferred source under the existing L policy.
"""

from types import SimpleNamespace

from .continuation_plan import ContinuationPlan
from .continuation_planning import native_plan_view
from .prompt_enrichment_runtime import (
    _answer_discharges_question,
    _correction_blocks_from_verified_source,
    _verified_native_answer_lineage,
)


def effective_correction_flags(
    repo,
    context,
    corrections,
    answers,
    *,
    native,
    artifacts,
    current_cycle_number,
    constraint_evidence,
    prospective=None,
):
    if context.retained_base != "L":
        raise ValueError("Native L source policy cannot replace the F frontier")
    sid, oid = context.scope.session_id, context.scope.organization_id
    plans = {}
    for row in repo.list_clarification_plans(sid, oid):
        if row.plan_payload.get("plan_version") != "3.0.0":
            continue
        plan = ContinuationPlan.model_validate(row.plan_payload)
        n = plan.allocated_current_frame_core.enrichment_cycle_number
        if n >= current_cycle_number:
            continue  # Future/unreplayed physical rows are not evidence.
        if plan.context != context:
            raise ValueError("Source plan has another continuation context")
        plans[n] = native_plan_view(plan)
    # The retained native prefix was fully verified before this function is
    # called. Reuse its original decoder/interpreter and answer-continuation
    # checks, rather than relabelling a new result as a legacy result.
    from .clarification import ClarificationPlan
    from .clarification_answers import ClarificationAnswerResult
    from .continuation_runtime import NativePrefixReader
    from .correction_enrichment import CorrectionReenrichmentResult

    admission = next(
        (p._f05_plan for p in plans.values() if p._f05_plan.trigger.trigger_kind == "ADMISSION"),
        None,
    )
    if admission is None:
        raise ValueError("Source policy requires the actual admitted prefix")
    head = admission.previous_head
    prefix = NativePrefixReader(repo, sid, oid, head.enrichment_cycle_number, head.revision_id)
    old_plan = ClarificationPlan.model_validate(
        prefix.get_clarification_plan(sid, head.plan_id, oid).plan_payload
    )
    old_answers = tuple(
        ClarificationAnswerResult.model_validate(a.result_payload) for a in native.answers
    )
    old_index, old_answer_plans, answer_steps = _verified_native_answer_lineage(
        prefix,
        session_id=sid,
        organization_id=oid,
        cycles=prefix.list_enrichment_cycles(sid, oid),
        answers=old_answers,
        current_plan=old_plan,
        artifacts=artifacts,
    )
    old_cycles = {c.cycle_number: c for c, _ in old_index.values()}
    plans.update({c.cycle_number: p for c, p in old_index.values()})
    old_corrections = tuple(
        CorrectionReenrichmentResult.model_validate(r.result_payload) for r in native.corrections
    )
    all_corrections = (*old_corrections, *(r for _, r, _, _ in corrections))
    flags = {r.content_hash: False for r in all_corrections}
    correction_cycles = {r.next_enrichment_cycle_number for r in all_corrections}
    adapters = [
        (a, c.cycle_number, p)
        for a in old_answers
        if (bound := old_answer_plans.get(a.content_hash)) is not None
        for c, p in (bound,)
    ]
    admitted_view = native_plan_view(admission)
    if (
        admitted_view.questions != old_plan.questions
        or admission.allocated_current_frame_core.revision_id != head.revision_id
        or admitted_view.unasked_evidence != old_plan.unasked_evidence
    ):
        raise ValueError("Admission cannot invent a native question continuation")
    answer_steps.add(head.enrichment_cycle_number)  # exact, verified neutral admission
    for _, result, _, _ in answers:
        number = result.previous_head.enrichment_cycle_number
        if number >= current_cycle_number:
            raise ValueError("Future answer cannot discharge a source")
        source = plans.get(number)
        if source is None or source.content_hash != result.plan_content_hash:
            raise ValueError("Answer lacks its actual source plan")
        # All supplied answers have been replayed through the native continuation
        # builder. KEEP answers may retain unrelated native questions, but cannot
        # themselves answer one or transfer their one-field release authority.
        answer_steps.add(number)
        if result.answer_kind == "NATIVE":
            payload = {
                name: getattr(result.native_result, name)
                for name in type(result.native_result).model_fields
            }
            payload.update(
                clarification_id=result.clarification_id,
                plan_content_hash=result.plan_content_hash,
                decision=result.decision,
            )
            adapters.append((SimpleNamespace(**payload), number, source))
    # Explicit KEEP resume is plan-neutral for the native question evidence.
    for number, plan in plans.items():
        actual = getattr(plan, "_f05_plan", None)
        if actual is None:
            continue
        if (
            actual.trigger.trigger_kind != "RESUME"
            or actual.trigger.request.resume_kind != "KEEP_RELEASE"
        ):
            continue
        old = plans.get(number - 1)
        if old is not None and old._f05_plan.native_base == actual.native_base:
            answer_steps.add(number - 1)
    current = SimpleNamespace(constraint_evidence=constraint_evidence)
    for correction in all_corrections:
        if correction.outcome != "DEFERRED":
            continue
        number = correction.next_enrichment_cycle_number
        origin = prospective if number == current_cycle_number else plans.get(number)
        if origin is None:
            raise ValueError("Deferred correction lacks its actual source plan")
        cycle = old_cycles.get(number) or SimpleNamespace(
            enrichment_cycle_id=correction.next_enrichment_cycle_id,
            cycle_number=number,
            specification_revision_id=correction.authoritative_revision.revision_id,
        )
        resolved = tuple(
            q
            for q in origin.questions
            if any(
                _answer_discharges_question(
                    a,
                    q,
                    origin=number,
                    answer_plan=(SimpleNamespace(cycle_number=n), p),
                    correction_cycles=correction_cycles,
                    answer_steps=answer_steps,
                )
                for a, n, p in adapters
            )
        )
        flags[correction.content_hash] = _correction_blocks_from_verified_source(
            correction,
            cycle=cycle,
            original_plan=origin,
            current_plan=current,
            resolved_questions=resolved,
        )
    return flags


def reproject_correction_audit(audit, flags):
    return tuple(
        d.model_copy(update={"blocks_progression": flags[d.content_hash]})
        if d.kind == "correction" and d.content_hash in flags
        else d
        for d in audit
    )
