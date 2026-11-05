"""Owner-approved read-only conversation projection; no new persistence or decisions."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from jewelai_domain.models import ImmutableModel
from jewelai_domain.models_v1_1 import AnyDesignRevision

from .continuation_preview import ContinuationStateV3, read_preview


class ConversationEvent(ImmutableModel):
    event_id: str
    kind: Literal["user", "question", "decision"]
    created_at: datetime
    text: str
    message_id: UUID | None = None
    cycle_number: int | None = None
    outcome: str | None = None


class ConversationResponse(ImmutableModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    session_id: UUID
    events: tuple[ConversationEvent, ...]
    state: ContinuationStateV3 | None
    revision: AnyDesignRevision


def read_conversation(service, sid, oid):
    """Reuse the scoped source-verified history reader and existing current-state DTO.

    Raw messages are explicitly just stored user text, not accepted facts. Decision
    outcomes are copied from verified records, never inferred from message wording.
    Timestamps order the transcript; equal timestamps use durable cycle/kind/ID ties.
    """
    with service.repository.read_enrichment_history(sid, oid) as repo:
        session = repo.get_design_session(sid, oid)
        cycles = (
            repo.list_enrichment_cycles(sid, oid)
            if session.knowledge_package_id is not None
            else ()
        )
        state = read_preview(service, sid, oid, _repository=repo) if cycles else None
        revision = repo.get_current_revision(sid, oid)
        events = [
            ConversationEvent(
                event_id=f"message:{m.message_id}",
                kind="user",
                created_at=m.created_at,
                text=m.content,
                message_id=m.message_id,
            )
            for m in repo.list_messages(sid, oid)
        ]
        if not cycles:
            return ConversationResponse(
                session_id=sid, events=tuple(events), state=None, revision=revision
            )
        numbers = {c.enrichment_cycle_id: c.cycle_number for c in cycles}
        for record in repo.list_clarification_plans(sid, oid):
            for index, question in enumerate(record.plan_payload["questions"]):
                text = (
                    question["offer"]["rendered_question"]
                    if question.get("question_kind") == "KEEP_RELEASE"
                    else question.get("native_question", question)["text"]
                )
                events.append(
                    ConversationEvent(
                        event_id=f"question:{record.clarification_plan_id}:{index}",
                        kind="question",
                        created_at=record.created_at,
                        text=text,
                        cycle_number=numbers[record.enrichment_cycle_id],
                    )
                )
        for record in (
            *repo.list_user_corrections(sid, oid),
            *repo.list_clarification_answers(sid, oid),
        ):
            payload = record.result_payload
            source = payload.get("source", {})
            message = source.get("message_id") or payload.get("request", {}).get("message_id")
            outcome = payload["outcome"]
            identity = getattr(record, "correction_record_id", None) or record.answer_record_id
            events.append(
                ConversationEvent(
                    event_id=f"decision:{identity}",
                    kind="decision",
                    created_at=record.created_at,
                    text=payload.get("decision", outcome),
                    outcome=outcome,
                    message_id=message,
                    cycle_number=numbers.get(getattr(record, "next_enrichment_cycle_id", None)),
                )
            )
        events.sort(
            key=lambda e: (
                e.created_at.replace(tzinfo=UTC) if e.created_at.tzinfo is None else e.created_at,
                e.cycle_number or 0,
                {"user": 0, "decision": 1, "question": 2}[e.kind],
                e.event_id,
            )
        )
        return ConversationResponse(
            session_id=sid, events=tuple(events), state=state, revision=revision
        )
