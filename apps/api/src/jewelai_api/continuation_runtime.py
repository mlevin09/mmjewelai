"""F05 explicitly admitted runtime over verified retained native history.

Native prefix records are read under their original decoders/interpreter. New
commands are reconstructed from actual scoped sources before a current view or
an atomic append is allowed. No provider or network work belongs in this path.
"""

import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

from jewelai_domain.continuation import (
    ContinuationContext,
    ContinuationFrame,
    ContinuationFrameCore,
)
from jewelai_domain.preservation import contract_hash
from jewelai_prompts.continuation import continuation_cycle

from .compatibility_projection import project_legacy_readiness
from .continuation_history import read_native_frame
from .continuation_plan import ContinuationPlan
from .continuation_planning import native_offers
from .continuation_preview import ContinuationReadError, NativePreviewQuestion


class NativePrefixReader:
    """Read view of actual old records; never mutate an attached session row."""

    def __init__(self, repo, sid, oid, number, revision_id):
        self.repo, self.sid, self.oid, self.number = repo, sid, oid, number
        self.revision = repo.get_revision(sid, revision_id, oid)

    def __getattr__(self, name):
        return getattr(self.repo, name)

    @contextmanager
    def read_enrichment_history(self, sid, oid):
        self.repo.get_design_session(sid, oid)
        yield self

    def get_design_session(self, sid, oid):
        row = self.repo.get_design_session(sid, oid)
        data = {c.key: getattr(row, c.key) for c in row.__mapper__.columns}
        data["current_revision_id"] = self.revision.revision_id
        return SimpleNamespace(**data)

    def get_current_revision(self, sid, oid):
        self.repo.get_design_session(sid, oid)
        return self.revision

    def list_revisions(self, sid, oid):
        return tuple(
            r for r in self.repo.list_revisions(sid, oid) if r.revision <= self.revision.revision
        )

    def list_enrichment_cycles(self, sid, oid):
        return tuple(
            c for c in self.repo.list_enrichment_cycles(sid, oid) if c.cycle_number <= self.number
        )

    def list_clarification_plans(self, sid, oid):
        ids = {c.enrichment_cycle_id for c in self.list_enrichment_cycles(sid, oid)}
        return tuple(
            p for p in self.repo.list_clarification_plans(sid, oid) if p.enrichment_cycle_id in ids
        )

    def list_clarification_answers(self, sid, oid):
        ids = {p.clarification_plan_id for p in self.list_clarification_plans(sid, oid)}
        return tuple(
            a
            for a in self.repo.list_clarification_answers(sid, oid)
            if a.clarification_plan_id in ids
        )

    def list_user_corrections(self, sid, oid):
        ids = {c.enrichment_cycle_id for c in self.list_enrichment_cycles(sid, oid)}
        return tuple(
            c
            for c in self.repo.list_user_corrections(sid, oid)
            if c.next_enrichment_cycle_id in ids
        )


def check_capacity(*artifacts):
    from jewelai_domain.clarification_state import evidence_bytes

    if any(len(evidence_bytes(a)) > 1_048_576 for a in artifacts):
        raise ContinuationReadError(
            422, "artifact_capacity_exceeded", "Continuation artifact exceeds capacity"
        )


def message_source(repo, sid, oid, mid):
    message = repo.get_message(sid, mid, oid)
    if message.actor != "user":
        raise ContinuationReadError(
            422, "invalid_clarification_answer", "An original user Message is required"
        )
    return message, hashlib.sha256(message.content.encode("utf-8")).hexdigest()


def request_hash(kind, context, request, sha):
    return contract_hash(
        f"jewelai.{kind}/{request.schema_version}",
        dict(
            scope=context.scope,
            retained_base=context.retained_base,
            request=request,
            source_message_sha256=sha,
        ),
    )


def native_context(service, repo, native, sid, oid):
    from .continuation_plan import NativeFPlanEvidence, NativeLPlanEvidence

    if native.session.question_artifact_version == "1.0.0":
        compat = project_legacy_readiness(service, repo, native, sid, oid)
        pins = compat.retained_artifact_pins
        base = NativeLPlanEvidence(
            retained_base="L",
            rule_decision=native.plan.rule_decision,
            native_questions=native.plan.questions,
            native_decision_audit=native.snapshot.decision_lineage,
        )
    else:
        pins = native.plan.artifact_pins
        base = NativeFPlanEvidence(
            retained_base="F",
            rule_decision=native.plan.rule_decision,
            native_questions=native.plan.questions,
            conflicts=native.plan.conflicts,
            cause_definitions=native.plan.cause_definitions,
            frontier_core=native.plan.frontier_core,
            availability_overlay=native.snapshot.enrichment_result.availability_overlay,
        )
    return ContinuationContext(
        scope=native.protection.scope,
        retained_base=base.retained_base,
        extension_profile="jewelai.prompt-enrichment.f05/1.0.0",
        release_pin=native.snapshot.knowledge_release.model_dump(),
        artifact_pins=pins.model_dump(),
        parser_interpreter_id="f05-1.2",
    ), base


def admission_plan(service, repo, native, sid, oid, request, sha, *, cycle_id, plan_id):
    context, base = native_context(service, repo, native, sid, oid)
    enriched = continuation_cycle(context, native.snapshot.enrichment_result, native.protection)
    core = ContinuationFrameCore(
        revision_id=native.frame.revision_id,
        revision_sha256=native.frame.revision_sha256,
        enrichment_cycle_id=cycle_id,
        enrichment_cycle_number=native.frame.enrichment_cycle_number + 1,
        enrichment_result_hash=enriched.content_hash,
        plan_id=plan_id,
    )
    compat = None
    if context.retained_base == "L":
        old = project_legacy_readiness(service, repo, native, sid, oid)
        p = old.model_dump(mode="json", exclude={"content_hash"})
        p.update(build_mode="embedded_plan", current_frame_core=core)
        compat = type(old)(
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
        dictionary_artifact_version=native.session.dictionary_artifact_version,
        question_artifact_version=native.session.question_artifact_version,
        rules_artifact_version=native.session.rules_artifact_version,
        locale=native.session.locale,
        role_id=native.session.role_id,
        native_base=base,
        historical_base_plan_ref=dict(id=native.frame.plan_id, hash=native.frame.plan_hash),
        questions=tuple(
            NativePreviewQuestion(
                question_kind="NATIVE", retained_base=context.retained_base, native_question=q
            )
            for q in base.native_questions
        ),
        unasked_evidence=native.plan.unasked_evidence,
        constraint_evidence=native.plan.constraint_evidence,
        protection_projection=native.protection,
        compatibility_projection=compat,
        trigger=dict(
            trigger_kind="ADMISSION",
            request=request,
            request_hash=request_hash("AdmissionRequest", context, request, sha),
            source_message_sha256=sha,
            previous_head=native.frame,
            legacy_interpreter_id="legacy-bc34-1.1",
            new_interpreter_id="f05-1.2",
        ),
    )
    plan = ContinuationPlan(**p, content_hash=contract_hash("jewelai.ClarificationPlan/3.0.0", p))
    return enriched, plan


def next_frame(previous, cycle, plan, sha):
    root = contract_hash(
        "jewelai.f05.history/1.0.0",
        dict(
            scope=plan.context.scope,
            context=plan.context,
            previous_head=previous,
            refs=(
                dict(
                    kind="revision",
                    id=str(plan.allocated_current_frame_core.revision_id),
                    hash=plan.allocated_current_frame_core.revision_sha256,
                ),
                dict(
                    kind="cycle", id=str(cycle.enrichment_cycle_id), hash=cycle.result.content_hash
                ),
                dict(
                    kind="plan",
                    id=str(plan.allocated_current_frame_core.plan_id),
                    hash=plan.content_hash,
                ),
                *(
                    ()
                    if plan.trigger.trigger_kind in {"ADMISSION", "RESUME"}
                    else (
                        dict(
                            kind=plan.trigger.trigger_kind.lower(),
                            id=str(plan.trigger.record_id),
                            hash=plan.trigger.result_hash,
                        ),
                    )
                ),
                dict(
                    kind="message",
                    id=str(
                        plan.trigger.request.message_id
                        if plan.trigger.trigger_kind in {"ADMISSION", "RESUME"}
                        else plan.trigger.message_id
                    ),
                    hash=sha,
                ),
            ),
        ),
    )
    return ContinuationFrame(
        **plan.allocated_current_frame_core.model_dump(),
        plan_hash=plan.content_hash,
        history_root_sha256=root,
    )


def replay_admitted(service, repo, sid, oid):
    cycles = repo.list_enrichment_cycles(sid, oid)
    new = tuple(c for c in cycles if c.result.enrichment_version == "3.0.0")
    if not new:
        return None
    first_index = cycles.index(new[0])
    if tuple(c.cycle_number for c in cycles) != tuple(range(1, len(cycles) + 1)) or any(
        c.result.enrichment_version != "3.0.0" for c in cycles[first_index:]
    ):
        raise ValueError("Continuation interval is not complete and append-only")
    plan_records = repo.list_clarification_plans(sid, oid)
    records = {p.enrichment_cycle_id: p for p in plan_records}
    if len(records) != len(plan_records) or set(records) != {c.enrichment_cycle_id for c in cycles}:
        raise ValueError("Continuation cycle/plan interval is incomplete")
    first = ContinuationPlan.model_validate(records[new[0].enrichment_cycle_id].plan_payload)
    if first.trigger.trigger_kind != "ADMISSION":
        raise ValueError("Continuation history lacks explicit admission")
    prefix = NativePrefixReader(
        repo, sid, oid, new[0].cycle_number - 1, first.previous_head.revision_id
    )
    native = read_native_frame(service, prefix, sid, oid)
    current = native.frame
    verified = []
    extras = []
    extra_answers = []
    answer_records = {r.answer_record_id: r for r in repo.list_clarification_answers(sid, oid)}
    correction_records = {r.correction_record_id: r for r in repo.list_user_corrections(sid, oid)}
    for cycle in new:
        record = records[cycle.enrichment_cycle_id]
        plan = ContinuationPlan.model_validate(record.plan_payload)
        if plan.previous_head != current:
            raise ValueError("Discontinuous continuation event")
        if plan.trigger.trigger_kind == "ADMISSION":
            if verified:
                raise ValueError("Continuation has repeated admission")
            _, sha = message_source(repo, sid, oid, plan.trigger.request.message_id)
            expected_cycle, expected_plan = admission_plan(
                service,
                prefix,
                native,
                sid,
                oid,
                plan.trigger.request,
                sha,
                cycle_id=cycle.enrichment_cycle_id,
                plan_id=record.clarification_plan_id,
            )
            if plan.trigger.request.expected_head != current:
                raise ValueError("Admission differs from its source frame")
        elif plan.trigger.trigger_kind == "CORRECTION":
            from .continuation_corrections import prepare_correction
            from .continuation_mutation import correction_plan, current_view
            from .continuation_results import ContinuationCorrectionResult

            row = correction_records.get(plan.trigger.record_id)
            if row is None:
                raise ValueError("Correction3 plan has no actual scoped record")
            result = ContinuationCorrectionResult.model_validate(row.result_payload)
            before_view, previous_plan, _ = current_view(
                service,
                repo,
                native,
                tuple(verified),
                prefix,
                extra_corrections=tuple(extras),
                extra_answers=tuple(extra_answers),
            )
            before = before_view.snapshot.revision
            actual = (
                repo.get_revision(sid, row.new_revision_id, oid) if row.new_revision_id else None
            )
            expected_result, offers = prepare_correction(
                service,
                repo,
                before_view,
                previous_plan,
                result.request,
                record_id=row.correction_record_id,
                cycle_id=cycle.enrichment_cycle_id,
                plan_id=record.clarification_plan_id,
                created_at=actual.created_at if actual else row.created_at,
                committed_revision=actual,
            )
            if result != expected_result or plan.trigger.result_hash != row.content_hash:
                raise ValueError(
                    "Correction3 differs from actual Message/proposal/transition replay"
                )
            if (
                plan.trigger.message_id != result.request.message_id
                or plan.trigger.message_sha256 != result.source_message_sha256
                or plan.trigger.request_hash != result.request_hash
                or result.next_enrichment_cycle_id != cycle.enrichment_cycle_id
            ):
                raise ValueError("Correction3 trigger/event binding mismatch")
            extras.append((row, result, before, result.authoritative_revision))
            expected_cycle = result.next_enrichment_result
            expected_plan = correction_plan(
                service,
                repo,
                before_view,
                previous_plan,
                result,
                offers,
                record_id=row.correction_record_id,
                plan_id=record.clarification_plan_id,
                verified_extras=tuple(extras),
                verified_answers=tuple(extra_answers),
                offer_history=native_offers(
                    prefix, tuple(verified), sid, oid, plan.context.retained_base
                ),
            )
            sha = result.source_message_sha256
        elif plan.trigger.trigger_kind == "ANSWER":
            from pydantic import TypeAdapter

            from .continuation_answers import prepare_answer
            from .continuation_mutation import answer_plan, current_view
            from .continuation_results import ContinuationAnswerResult

            row = answer_records.get(plan.trigger.record_id)
            if row is None:
                raise ValueError("Answer3 plan has no actual scoped record")
            result = TypeAdapter(ContinuationAnswerResult).validate_python(row.result_payload)
            before_view, previous_plan, _ = current_view(
                service,
                repo,
                native,
                tuple(verified),
                prefix,
                extra_corrections=tuple(extras),
                extra_answers=tuple(extra_answers),
            )
            intent_map = {i.intent_id: (i, r) for _, r, _, _ in extras for i in r.keep_intents}
            actual = (
                repo.get_revision(sid, row.new_revision_id, oid) if row.new_revision_id else None
            )
            expected_result = prepare_answer(
                service,
                repo,
                before_view,
                previous_plan,
                result.request,
                cycle_id=cycle.enrichment_cycle_id,
                created_at=actual.created_at if actual else row.created_at,
                intents=intent_map,
                committed_revision=actual,
            )
            if result != expected_result or result.content_hash != plan.trigger.result_hash:
                raise ValueError(
                    "Answer3 differs from actual question/intent/source/transition replay"
                )
            if (
                plan.trigger.message_id != result.request.message_id
                or plan.trigger.message_sha256 != result.message_sha256
                or plan.trigger.request_hash != result.request_hash
            ):
                raise ValueError("Answer3 trigger/source bindings mismatch")
            expected_cycle = result.next_enrichment_result
            expected_plan = answer_plan(
                service,
                repo,
                before_view,
                previous_plan,
                result,
                cycle_id=cycle.enrichment_cycle_id,
                plan_id=record.clarification_plan_id,
                verified_extras=tuple(extras),
                verified_answers=tuple(extra_answers),
                offer_history=native_offers(
                    prefix, tuple(verified), sid, oid, plan.context.retained_base
                ),
            )
            extra_answers.append(
                (
                    row,
                    result,
                    before_view.snapshot.revision,
                    result.resulting_revision or before_view.snapshot.revision,
                )
            )
            sha = result.message_sha256
        elif plan.trigger.trigger_kind == "RESUME":
            from .continuation_mutation import current_view
            from .continuation_resume import prepare_resume

            before_view, previous_plan, _ = current_view(
                service,
                repo,
                native,
                tuple(verified),
                prefix,
                extra_corrections=tuple(extras),
                extra_answers=tuple(extra_answers),
            )
            intent_map = {i.intent_id: (i, r) for _, r, _, _ in extras for i in r.keep_intents}
            historical_offers = (
                tuple(
                    q.offer
                    for _, p, _ in verified
                    for q in p.questions
                    if q.question_kind == "KEEP_RELEASE"
                )
                if plan.trigger.request.resume_kind == "KEEP_RELEASE"
                else native_offers(prefix, tuple(verified), sid, oid, plan.context.retained_base)
            )
            expected_cycle, expected_plan = prepare_resume(
                service,
                repo,
                before_view,
                previous_plan,
                plan.trigger.request,
                cycle_id=cycle.enrichment_cycle_id,
                plan_id=record.clarification_plan_id,
                intents=intent_map,
                offers=historical_offers,
            )
            _, sha = message_source(repo, sid, oid, plan.trigger.request.message_id)
        else:
            raise ValueError("Unsupported continuation event")
        if expected_cycle != cycle.result or expected_plan != plan:
            raise ValueError("Continuation differs from actual native/source replay")
        current = next_frame(current, cycle, plan, sha)
        verified.append((cycle, plan, current))
    if repo.get_current_revision(sid, oid).revision_id != current.revision_id:
        raise ValueError("Canonical state changed without a continuation event")
    referenced = {
        p.trigger.record_id for _, p, _ in verified if p.trigger.trigger_kind == "CORRECTION"
    }
    if referenced != {
        r.correction_record_id
        for r in correction_records.values()
        if r.result_payload.get("correction_version") == "3.0.0"
    }:
        raise ValueError("Correction3 interval has an orphan or missing event")
    referenced_answers = {
        p.trigger.record_id for _, p, _ in verified if p.trigger.trigger_kind == "ANSWER"
    }
    if referenced_answers != {
        r.answer_record_id
        for r in answer_records.values()
        if r.result_payload.get("answer_version") == "3.0.0"
    }:
        raise ValueError("Answer3 interval has an orphan or missing event")
    return native, tuple(verified), prefix, tuple(extras), tuple(extra_answers)


def admitted_view(service, repo, sid, oid):
    replay = replay_admitted(service, repo, sid, oid)
    if replay is None:
        return None
    native, verified, prefix, extras, extra_answers = replay
    from .continuation_mutation import current_view

    return current_view(
        service,
        repo,
        native,
        verified,
        prefix,
        extra_corrections=extras,
        extra_answers=extra_answers,
    )


def admit(service, sid, oid, request, *, principal_id):

    def build(repo):
        _, sha = message_source(repo, sid, oid, request.message_id)
        replay = replay_admitted(service, repo, sid, oid)
        if replay is not None:
            _, verified, _, _, _ = replay
            for _cycle, plan, frame in verified:
                if (
                    plan.trigger.trigger_kind == "ADMISSION"
                    and plan.trigger.request.request_id == request.request_id
                ):
                    if plan.trigger.request != request or plan.trigger.request_hash != request_hash(
                        "AdmissionRequest", plan.context, request, sha
                    ):
                        raise ContinuationReadError(
                            409,
                            "clarification_conflict",
                            "Admission identity already has another request",
                        )
                    return dict(replayed=True, committed_frame=frame, plan=plan)
            raise ContinuationReadError(
                409, "already_admitted", "Session already has explicit continuation admission"
            )
        if not service.continuation_enabled:
            raise ContinuationReadError(
                409, "continuation_unavailable", "Continuation writes are disabled"
            )
        native = read_native_frame(service, repo, sid, oid)
        if request.expected_head != native.frame:
            raise ContinuationReadError(
                409, "stale_clarification_plan", "Current workflow frame changed"
            )
        cycle_id, plan_id = service._uuid(), service._uuid()
        cycle, plan = admission_plan(
            service, repo, native, sid, oid, request, sha, cycle_id=cycle_id, plan_id=plan_id
        )
        return dict(
            cycle_id=cycle_id,
            cycle_number=native.frame.enrichment_cycle_number + 1,
            cycle_result=cycle,
            plan_id=plan_id,
            plan_payload=plan.model_dump(mode="json"),
            plan=plan,
            replayed=False,
        )

    from .continuation_preview import read_preview

    committed = service.repository.commit_continuation(
        sid,
        oid,
        build,
        principal_id=principal_id,
        created_at=service._clock(),
        verify=lambda repo: read_preview(service, sid, oid, _repository=repo),
    )
    state = committed["current_state"]
    frame = committed.get("committed_frame") or state.current_frame
    plan = committed["plan"]
    result_hash = contract_hash(
        "jewelai.AdmissionResult/1.0.0",
        dict(
            request_hash=plan.trigger.request_hash,
            emitted_plan_id=frame.plan_id,
            emitted_plan_hash=frame.plan_hash,
        ),
    )
    return dict(
        schema_version="3.0.0",
        command_kind="ADMISSION",
        committed_result_hash=result_hash,
        committed_frame=frame,
        current_state=state,
        replayed=committed["replayed"],
    )


def correct(service, sid, oid, request, *, principal_id):
    """Scoped Correction3 duplicate lookup, full-frame CAS and one atomic append."""
    from .continuation_corrections import prepare_correction
    from .continuation_mutation import correction_plan, current_view
    from .continuation_preview import read_preview
    from .continuation_results import ContinuationCorrectionResult

    created_at = service._clock()

    def build(repo):
        _, sha = message_source(repo, sid, oid, request.message_id)
        replay = replay_admitted(service, repo, sid, oid)
        if replay is None:
            raise ContinuationReadError(
                409, "unsupported_workflow_version", "Explicit continuation admission is required"
            )
        origin, verified, prefix, extras, extra_answers = replay
        view, previous, _ = current_view(
            service,
            repo,
            origin,
            verified,
            prefix,
            extra_corrections=extras,
            extra_answers=extra_answers,
        )
        all_records = repo.list_user_corrections(sid, oid)
        for row in all_records:
            if row.result_payload.get("correction_version") != "3.0.0":
                continue
            result = ContinuationCorrectionResult.model_validate(row.result_payload)
            if result.request_id == request.request_id:
                if result.request != request or result.request_hash != request_hash(
                    "CorrectionRequest", result.context, request, sha
                ):
                    raise ContinuationReadError(
                        409,
                        "correction_conflict",
                        "Correction identity already has another request",
                    )
                committed_frame = next(
                    frame
                    for _, p, frame in verified
                    if p.trigger.trigger_kind == "CORRECTION"
                    and p.trigger.record_id == row.correction_record_id
                )
                return dict(
                    replayed=True, committed_frame=committed_frame, correction_result=result
                )
        if any(r.source_message_id == str(request.message_id) for r in all_records):
            raise ContinuationReadError(
                409, "source_already_consumed", "Correction source already has a durable result"
            )
        if not service.continuation_enabled:
            raise ContinuationReadError(
                409, "continuation_unavailable", "Continuation writes are disabled"
            )
        if request.expected_head != view.frame:
            raise ContinuationReadError(
                409, "stale_clarification_plan", "Current workflow frame changed"
            )
        record_id, cycle_id, plan_id = service._uuid(), service._uuid(), service._uuid()
        result, offers = prepare_correction(
            service,
            repo,
            view,
            previous,
            request,
            record_id=record_id,
            cycle_id=cycle_id,
            plan_id=plan_id,
            created_at=created_at,
        )
        staged_ref = SimpleNamespace(
            correction_record_id=record_id, content_hash=result.content_hash
        )
        plan = correction_plan(
            service,
            repo,
            view,
            previous,
            result,
            offers,
            record_id=record_id,
            plan_id=plan_id,
            verified_extras=(
                *extras,
                (staged_ref, result, view.snapshot.revision, result.authoritative_revision),
            ),
            verified_answers=extra_answers,
            offer_history=native_offers(prefix, verified, sid, oid, previous.context.retained_base),
        )
        check_capacity(result, plan)
        return dict(
            replayed=False,
            cycle_id=cycle_id,
            cycle_number=result.next_enrichment_cycle_number,
            cycle_result=result.next_enrichment_result,
            plan_id=plan_id,
            plan_payload=plan.model_dump(mode="json"),
            plan=plan,
            revision=result.authoritative_revision if result.new_revision_id is not None else None,
            correction_result=result,
            record_id=record_id,
        )

    committed = service.repository.commit_continuation(
        sid,
        oid,
        build,
        principal_id=principal_id,
        created_at=created_at,
        verify=lambda repo: read_preview(service, sid, oid, _repository=repo),
    )
    state = committed["current_state"]
    return dict(
        schema_version="3.0.0",
        command_kind="CORRECTION",
        committed_result_hash=committed["correction_result"].content_hash,
        committed_frame=committed.get("committed_frame") or state.current_frame,
        current_state=state,
        replayed=committed["replayed"],
    )


def answer(service, sid, oid, request, *, principal_id):
    """Answer3 idempotency and consent are resolved under the current tenant lock."""
    from pydantic import TypeAdapter

    from .continuation_answers import prepare_answer
    from .continuation_mutation import answer_plan, current_view
    from .continuation_preview import read_preview
    from .continuation_results import ContinuationAnswerResult

    created_at = service._clock()

    def build(repo):
        _, sha = message_source(repo, sid, oid, request.message_id)
        replay = replay_admitted(service, repo, sid, oid)
        if replay is None:
            raise ContinuationReadError(
                409, "unsupported_workflow_version", "Explicit continuation admission is required"
            )
        origin, verified, prefix, extras, extra_answers = replay
        view, previous, _ = current_view(
            service,
            repo,
            origin,
            verified,
            prefix,
            extra_corrections=extras,
            extra_answers=extra_answers,
        )
        for row in repo.list_clarification_answers(sid, oid):
            matches_id = row.answer_record_id == request.answer_id
            matches_question = (
                row.plan_content_hash == request.expected_head.plan_hash
                and row.clarification_id == request.clarification_id
            )
            if not (matches_id or matches_question):
                continue
            if row.result_payload.get("answer_version") != "3.0.0":
                raise ContinuationReadError(
                    409, "clarification_conflict", "Answer identity belongs to retained history"
                )
            result = TypeAdapter(ContinuationAnswerResult).validate_python(row.result_payload)
            if result.request != request or result.request_hash != request_hash(
                "AnswerRequest", result.context, request, sha
            ):
                raise ContinuationReadError(
                    409, "clarification_conflict", "Question already has another immutable decision"
                )
            committed_frame = next(
                frame
                for _, p, frame in verified
                if p.trigger.trigger_kind == "ANSWER"
                and p.trigger.record_id == row.answer_record_id
            )
            return dict(replayed=True, committed_frame=committed_frame, answer_result=result)
        if not service.continuation_enabled:
            raise ContinuationReadError(
                409, "continuation_unavailable", "Continuation writes are disabled"
            )
        if request.expected_head != view.frame:
            raise ContinuationReadError(
                409, "stale_clarification_plan", "Current workflow frame changed"
            )
        cycle_id, plan_id = service._uuid(), service._uuid()
        intents = {i.intent_id: (i, r) for _, r, _, _ in extras for i in r.keep_intents}
        result = prepare_answer(
            service,
            repo,
            view,
            previous,
            request,
            cycle_id=cycle_id,
            created_at=created_at,
            intents=intents,
        )
        plan = answer_plan(
            service,
            repo,
            view,
            previous,
            result,
            cycle_id=cycle_id,
            plan_id=plan_id,
            verified_extras=extras,
            verified_answers=extra_answers,
            offer_history=native_offers(prefix, verified, sid, oid, previous.context.retained_base),
        )
        check_capacity(result, plan)
        return dict(
            replayed=False,
            record_id=result.answer_id,
            cycle_id=cycle_id,
            cycle_number=view.frame.enrichment_cycle_number + 1,
            cycle_result=result.next_enrichment_result,
            plan_id=plan_id,
            plan_payload=plan.model_dump(mode="json"),
            plan=plan,
            revision=result.resulting_revision,
            answer_result=result,
        )

    committed = service.repository.commit_continuation(
        sid,
        oid,
        build,
        principal_id=principal_id,
        created_at=created_at,
        verify=lambda repo: read_preview(service, sid, oid, _repository=repo),
    )
    state = committed["current_state"]
    return dict(
        schema_version="3.0.0",
        command_kind="ANSWER",
        committed_result_hash=committed["answer_result"].content_hash,
        committed_frame=committed.get("committed_frame") or state.current_frame,
        current_state=state,
        replayed=committed["replayed"],
    )


def resume(service, sid, oid, request, *, principal_id):
    from .continuation_mutation import current_view
    from .continuation_preview import read_preview
    from .continuation_results import derive_resume_result
    from .continuation_resume import prepare_resume

    def build(repo):
        _, sha = message_source(repo, sid, oid, request.message_id)
        replay = replay_admitted(service, repo, sid, oid)
        if replay is None:
            raise ContinuationReadError(
                409, "unsupported_workflow_version", "Explicit admission required"
            )
        origin, verified, prefix, extras, extra_answers = replay
        view, previous, _ = current_view(
            service,
            repo,
            origin,
            verified,
            prefix,
            extra_corrections=extras,
            extra_answers=extra_answers,
        )
        expected_hash = request_hash("ResumeRequest", previous.context, request, sha)
        for _, p, frame in verified:
            if (
                p.trigger.trigger_kind == "RESUME"
                and p.trigger.request.request_id == request.request_id
            ):
                if p.trigger.request != request or p.trigger.request_hash != expected_hash:
                    raise ContinuationReadError(
                        409, "clarification_conflict", "Resume identity has another request"
                    )
                return dict(replayed=True, committed_frame=frame, plan=p)
        if not service.continuation_enabled:
            raise ContinuationReadError(
                409, "continuation_unavailable", "Continuation writes are disabled"
            )
        if request.expected_head != view.frame:
            raise ContinuationReadError(
                409, "stale_clarification_plan", "Current workflow frame changed"
            )
        cycle_id, plan_id = service._uuid(), service._uuid()
        intents = {i.intent_id: (i, r) for _, r, _, _ in extras for i in r.keep_intents}
        offers = (
            tuple(
                q.offer
                for _, p, _ in verified
                for q in p.questions
                if q.question_kind == "KEEP_RELEASE"
            )
            if request.resume_kind == "KEEP_RELEASE"
            else native_offers(prefix, verified, sid, oid, previous.context.retained_base)
        )
        cycle, plan = prepare_resume(
            service,
            repo,
            view,
            previous,
            request,
            cycle_id=cycle_id,
            plan_id=plan_id,
            intents=intents,
            offers=offers,
        )
        # The exact result is derived from an already sealed plan, but verified
        # before committing so a non-emitting resume cannot partially append.
        check_capacity(cycle, plan, derive_resume_result(plan))
        return dict(
            replayed=False,
            cycle_id=cycle_id,
            cycle_number=view.frame.enrichment_cycle_number + 1,
            cycle_result=cycle,
            plan_id=plan_id,
            plan_payload=plan.model_dump(mode="json"),
            plan=plan,
        )

    committed = service.repository.commit_continuation(
        sid,
        oid,
        build,
        principal_id=principal_id,
        created_at=service._clock(),
        verify=lambda repo: read_preview(service, sid, oid, _repository=repo),
    )
    state = committed["current_state"]
    return dict(
        schema_version="3.0.0",
        command_kind="RESUME",
        committed_result_hash=derive_resume_result(committed["plan"]).content_hash,
        committed_frame=committed.get("committed_frame") or state.current_frame,
        current_state=state,
        replayed=committed["replayed"],
    )
