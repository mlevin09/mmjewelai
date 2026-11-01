"""F05 explicitly admitted runtime over verified retained native history.

Native prefix records are read under their original decoders/interpreter. New
commands are reconstructed from actual scoped sources before a current view or
an atomic append is allowed. No provider or network work belongs in this path.
"""

import hashlib
from contextlib import contextmanager
from dataclasses import replace
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
    from .compatibility_projection import project_legacy_readiness
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
                dict(kind="message", id=str(plan.trigger.request.message_id), hash=sha),
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
    for cycle in new:
        plan = ContinuationPlan.model_validate(records[cycle.enrichment_cycle_id].plan_payload)
        if plan.previous_head != current or plan.trigger.trigger_kind != "ADMISSION" or verified:
            raise ValueError("Unsupported or discontinuous continuation event")
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
            plan_id=records[cycle.enrichment_cycle_id].clarification_plan_id,
        )
        if (
            plan.trigger.request.expected_head != current
            or expected_cycle != cycle.result
            or expected_plan != plan
        ):
            raise ValueError("Continuation admission differs from actual native/source replay")
        current = next_frame(current, cycle, plan, sha)
        verified.append((cycle, plan, current))
    if repo.get_current_revision(sid, oid) != native.snapshot.revision:
        raise ValueError("Admission changed canonical state without an event")
    return native, tuple(verified), prefix


def admitted_view(service, repo, sid, oid):
    replay = replay_admitted(service, repo, sid, oid)
    if replay is None:
        return None
    native, verified, prefix = replay
    cycle, plan, frame = verified[-1]
    snapshot = native.snapshot.model_copy(
        update=dict(
            enrichment_cycle_id=cycle.enrichment_cycle_id,
            latest_enrichment_cycle_id=cycle.enrichment_cycle_id,
            enrichment_cycle_number=cycle.cycle_number,
            enrichment_result=cycle.result,
            artifact_versions=native.snapshot.artifact_versions.model_copy(
                update={"enrichment_version": "3.0.0"}
            ),
        )
    )
    compat = None
    if plan.context.retained_base == "L":
        original = project_legacy_readiness(service, prefix, native, sid, oid)
        p = original.model_dump(mode="json", exclude={"content_hash"})
        p.update(evidence_head=frame, current_frame_core=plan.allocated_current_frame_core)
        compat = type(original)(
            **p, content_hash=contract_hash("jewelai.CompatibilityReadinessProjection/1.0.0", p)
        )
    else:
        from .clarification_v2 import ClarificationPlanV2, seal_frontier

        adapted = SimpleNamespace(
            plan_id=frame.plan_id,
            content_hash=plan.content_hash,
            enrichment_cycle_number=cycle.cycle_number,
            questions=plan.native_base.native_questions,
            frontier_core=plan.native_base.frontier_core,
            cause_definitions=plan.native_base.cause_definitions,
        )
        oldplans = [
            ClarificationPlanV2.model_validate(p.plan_payload)
            for p in prefix.list_clarification_plans(sid, oid)
        ]
        snapshot = snapshot.model_copy(
            update={"effective_unresolved_frontier": seal_frontier(adapted, oldplans)}
        )
    return (
        replace(native, frame=frame, snapshot=snapshot, protection=plan.protection_projection),
        plan,
        compat,
    )


def admit(service, sid, oid, request, *, principal_id):
    if not getattr(service, "continuation_enabled", False):
        raise ContinuationReadError(
            409, "continuation_unavailable", "Explicit continuation capability is unavailable"
        )

    def build(repo):
        _, sha = message_source(repo, sid, oid, request.message_id)
        replay = replay_admitted(service, repo, sid, oid)
        if replay is not None:
            _, verified, _ = replay
            for _cycle, plan, frame in verified:
                if plan.trigger.request.request_id == request.request_id:
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
