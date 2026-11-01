"""Read-only F05 bootstrap from exact retained native history.

No interpreter mutation, new release selection, pin initialization or Message
replay is used to construct canonical state. Original validators run first.
"""

import hashlib
import re
from copy import copy
from dataclasses import dataclass
from datetime import UTC
from uuid import UUID

from jewelai_domain.clarification_state import EvidenceScope, evidence_hash
from jewelai_domain.continuation import ContinuationFrame
from jewelai_domain.models import MessageSource
from jewelai_domain.preservation import (
    build_preservation_root,
    contract_hash,
    initial_protection_projection,
)
from pydantic import BaseModel

from .clarification import ClarificationPlan
from .clarification_answers import ClarificationAnswer, _hash, process_clarification_answer
from .prompt_enrichment_runtime import build_final_prompt_snapshot


@dataclass(frozen=True)
class NativeContinuationFrame:
    frame: ContinuationFrame
    snapshot: object
    plan: object
    session: object
    roots: tuple
    protection: object
    corrections: tuple
    answers: tuple


def _message_sources(value):
    if isinstance(value, MessageSource):
        yield value.message_id
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _message_sources(getattr(value, name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _message_sources(item)


def _native_roots(repo, sid, oid, plan):
    roots = []
    for evidence in plan.constraint_evidence:
        if not (
            evidence.status == "active"
            and evidence.kind == "preservation"
            and evidence.semantic_subject == "component.center_stone"
        ):
            continue
        message = repo.get_message(sid, UUID(evidence.source.message_id), oid)
        if (
            message.actor != "user"
            or evidence.source.recorded_at
            != (
                message.created_at.replace(tzinfo=UTC)
                if message.created_at.tzinfo is None
                else message.created_at
            )
            or message.content[evidence.source_span_start : evidence.source_span_end]
            != evidence.original_wording
        ):
            raise ValueError("Preservation source span does not match actual user Message")
        source_revision = repo.get_revision(sid, evidence.source_revision_id, oid)
        source_cycle = repo.get_enrichment_cycle(sid, evidence.source_enrichment_cycle_id, oid)
        if source_cycle.specification_revision_id != source_revision.revision_id:
            raise ValueError("Preservation source cycle/revision does not match actual history")
        field = (
            "shape" if re.search(r"\bshape\b|\bформ\w*", evidence.original_wording, re.I) else None
        )
        roots.append(
            build_preservation_root(
                evidence_id=evidence.evidence_id,
                evidence_hash=evidence.content_hash,
                source_revision=source_revision,
                source_cycle_id=evidence.source_enrichment_cycle_id,
                field=field,
            )
        )
    return tuple(roots)


def _legacy_answer_source_ids(service, repo, sid, oid, answers, plans):
    """Verify frozen Answer1 source hashes against actual same-session Messages.

    Non-mutating Answer1 did not serialize Source. Its answer_hash nevertheless
    commits the exact Message ID/time. Resolve that commitment without reading or
    interpreting unrelated message text; do not invent a new historical source.
    """
    if not answers:
        return set()
    sources = repo.list_user_message_source_refs(sid, oid)
    plan_by_hash = {p.content_hash: ClarificationPlan.model_validate(p.plan_payload) for p in plans}
    verified = repo.restore_pinned_knowledge_runtime(
        sid,
        oid,
        service.artifact_store,
        active_release=service.active_release,
        validation_report=service.validation_report,
    )
    consumed = set()
    for record in answers:
        result = record.result_payload
        selected = result["selected_option"]
        payload = dict(
            session_id=sid,
            plan_content_hash=result["plan_content_hash"],
            clarification_id=result["clarification_id"],
            decision=result["decision"],
            selected_option=selected["value"] if selected else None,
            expected_revision_id=result["previous_revision_id"],
            knowledge_package_id=result["knowledge_package_id"],
            knowledge_artifact_version=result["knowledge_artifact_version"],
            knowledge_runtime_sha256=result["knowledge_runtime_sha256"],
            knowledge_validation_report_sha256=result["knowledge_validation_report_sha256"],
        )
        matches = []
        for mid, created_at in sources:
            source = MessageSource(
                message_id=str(mid),
                recorded_at=(
                    created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
                ),
            )
            candidate = ClarificationAnswer(**payload, source=source)
            if _hash(candidate.model_dump(mode="json")) == record.answer_hash:
                matches.append(candidate)
        if len(matches) != 1:
            raise ValueError("Legacy answer source commitment has no unique scoped Message")
        answer = matches[0]
        consumed.add(answer.source.message_id)
        plan = plan_by_hash.get(record.plan_content_hash)
        if plan is None:
            raise ValueError("Legacy answer has no scoped original plan")
        before = repo.get_revision(sid, record.previous_revision_id, oid)
        actual = (
            repo.get_revision(sid, record.new_revision_id, oid)
            if record.new_revision_id is not None
            else None
        )
        created_at = actual.created_at if actual is not None else record.created_at
        replayed = process_clarification_answer(
            plan,
            answer,
            authoritative_session_id=sid,
            current_revision=before,
            active_release=verified,
            dictionary=service.artifacts.dictionary,
            questions=service.artifacts.questions,
            rules=service.artifacts.rules,
            created_at=created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at,
        )
        replay = replayed.model_dump(mode="json", exclude={"content_hash"})
        if record.new_revision_id is not None:
            generated = replayed.resulting_revision
            if generated is None or generated.model_dump(
                exclude={"revision_id"}
            ) != actual.model_dump(exclude={"revision_id"}):
                raise ValueError("Legacy accepted answer has a different canonical transition")
            replay["new_revision_id"] = str(actual.revision_id)
            replay["resulting_revision"] = actual.model_dump(mode="json")
        if result != {**replay, "content_hash": _hash(replay)}:
            raise ValueError("Legacy answer does not match actual source/decision replay")
    return consumed


def read_native_frame(service, repository, session_id, organization_id):
    """Caller supplies one scoped locked_reader; no command transaction is opened."""
    service = copy(service._for_session(session_id, organization_id, repository=repository))
    service.repository = repository
    session = repository.get_design_session(session_id, organization_id)
    if service._is_f04:
        from .prompt_enrichment_runtime_v2 import _snapshot

        snapshot, plan, _, _ = _snapshot(service, repository, session_id, organization_id)
    else:
        snapshot = build_final_prompt_snapshot(
            repository,
            session_id=session_id,
            organization_id=organization_id,
            artifacts=service.artifacts,
            artifact_store=service.artifact_store,
            active_release=service.active_release,
            validation_report=service.validation_report,
        )
        row = repository.get_clarification_plan_for_cycle(
            session_id, snapshot.enrichment_cycle_id, organization_id
        )
        plan = ClarificationPlan.model_validate(row.plan_payload)
    cycles = repository.list_enrichment_cycles(session_id, organization_id)
    plans = repository.list_clarification_plans(session_id, organization_id)
    answers = repository.list_clarification_answers(session_id, organization_id)
    corrections = repository.list_user_corrections(session_id, organization_id)
    revisions = repository.list_revisions(session_id, organization_id)
    if tuple(c.cycle_number for c in cycles) != tuple(range(1, len(cycles) + 1)):
        raise ValueError("Native continuation history is not append-only")
    if {p.enrichment_cycle_id for p in plans} != {c.enrichment_cycle_id for c in cycles}:
        raise ValueError("Native continuation has a missing cycle plan")
    by_cycle = {p.enrichment_cycle_id: p for p in plans}
    refs = []
    sources = (
        set()
        if service._is_f04
        else _legacy_answer_source_ids(
            service, repository, session_id, organization_id, answers, plans
        )
    )
    for revision in revisions:
        refs.append(
            dict(kind="revision", id=str(revision.revision_id), hash=evidence_hash(revision))
        )
        sources.update(_message_sources(revision))
    for cycle in cycles:
        record = by_cycle[cycle.enrichment_cycle_id]
        refs.extend(
            (
                dict(
                    kind="cycle", id=str(cycle.enrichment_cycle_id), hash=cycle.result.content_hash
                ),
                dict(kind="plan", id=str(record.clarification_plan_id), hash=record.content_hash),
            )
        )
    for kind, records in (("answer", answers), ("correction", corrections)):
        for record in sorted(
            records,
            key=lambda r: str(
                getattr(r, "answer_record_id", getattr(r, "correction_record_id", None))
            ),
        ):
            record_id = getattr(
                record, "answer_record_id", getattr(record, "correction_record_id", None)
            )
            refs.append(dict(kind=kind, id=str(record_id), hash=record.content_hash))
            source = record.result_payload.get("source")
            if source and source.get("kind") == "message":
                sources.add(source["message_id"])
    for evidence in plan.constraint_evidence:
        sources.add(evidence.source.message_id)
    for record in corrections:
        sources.add(record.source_message_id)
    for record in plans:
        trigger = record.plan_payload.get("trigger", {})
        if trigger.get("message_id"):
            sources.add(trigger["message_id"])
    for mid in sorted(sources):
        if mid == f"session:{session_id}:create":
            # The existing empty-session control source is not a user Message.
            continue
        message = repository.get_message(session_id, UUID(mid), organization_id)
        refs.append(
            dict(
                kind="message",
                id=str(message.message_id),
                hash=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
            )
        )
    root = contract_hash(
        "jewelai.f05.history/1.0.0",
        dict(
            scope=dict(
                organization_id=str(organization_id),
                session_id=str(session_id),
                design_id=str(snapshot.revision.design_id),
            ),
            artifact_versions=snapshot.artifact_versions.model_dump(mode="json"),
            knowledge_release=snapshot.knowledge_release.model_dump(mode="json"),
            refs=refs,
        ),
    )
    latest = cycles[-1]
    frame = ContinuationFrame(
        revision_id=snapshot.revision.revision_id,
        revision_sha256=evidence_hash(snapshot.revision),
        enrichment_cycle_id=latest.enrichment_cycle_id,
        enrichment_cycle_number=latest.cycle_number,
        enrichment_result_hash=latest.result.content_hash,
        plan_id=by_cycle[latest.enrichment_cycle_id].clarification_plan_id,
        plan_hash=plan.content_hash,
        history_root_sha256=root,
    )
    roots = _native_roots(repository, session_id, organization_id, plan)
    scope = EvidenceScope(
        organization_id=organization_id,
        session_id=session_id,
        design_id=snapshot.revision.design_id,
    )
    protection = initial_protection_projection(snapshot.revision, scope, roots)
    return NativeContinuationFrame(
        frame, snapshot, plan, session, roots, protection, tuple(corrections), tuple(answers)
    )
