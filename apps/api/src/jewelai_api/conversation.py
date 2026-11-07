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
                    text=_decision_text(payload, session.locale),
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


# Presentation of already source-verified records, not another interpretation or
# acceptance boundary. APPLIED can mean a subset; Matrix APPLIED alone is not a
# committed transition. Original records/hashes and the outcome badge are unchanged.
def _decision_text(payload, locale):
    original = payload.get("decision", payload["outcome"])
    if "correction_version" not in payload:
        return original
    ru = locale == "ru"
    if payload.get("reason") == "keep_release_required":
        return (
            "Изменение сохранённого свойства ожидает подтверждения; значение не изменено."
            if ru
            else "A preserved-property change awaits confirmation; the value is unchanged."
        )
    dispositions = payload.get("correction_evaluation", {}).get("dispositions", [])
    committed = payload["outcome"] in {"APPLIED", "NO_CHANGE"}
    accepted = {
        (
            d["candidate"]["evidence"]["start"],
            d["candidate"]["evidence"]["end"],
            d["candidate"].get("target"),
            d["candidate"]["subject"],
        )
        for d in dispositions
        if committed and d["outcome"] in {"APPLIED", "KEPT", "NO_CHANGE"}
    }
    labels = {
        "jewelry_type": ("jewelry type", "тип украшения"),
        "metal.material": ("metal", "металл"),
        "metal.color": ("metal color", "цвет металла"),
        "center_stone.material": ("center stone material", "материал центрального камня"),
        "center_stone.shape": ("center stone shape", "форма центрального камня"),
        "center_stone.dimensions": ("center stone dimensions", "размеры центрального камня"),
        "center_stone.setting": ("center stone setting", "закрепка центрального камня"),
        "style": ("style", "стиль"),
    }
    reasons = {
        "target_not_supported_by_parser": (
            "the current contract cannot apply this value; clarify with a supported value",
            "текущий контракт не поддерживает это значение; уточните поддерживаемое значение",
        ),
        "component_target_not_representable": (
            "the named component has no supported canonical target",
            "указанный компонент не имеет поддерживаемого канонического поля",
        ),
        "ambiguous_candidate": ("clarify the intended value", "уточните выбранное значение"),
        "preference_requires_acceptance": (
            "explicit acceptance is still required",
            "требуется явное принятие предпочтения",
        ),
    }
    details = []
    for d in dispositions:
        c = d["candidate"]
        occurrence = (c["evidence"]["start"], c["evidence"]["end"], c.get("target"), c["subject"])
        if d["outcome"] not in {"DEFERRED", "BLOCKED"} or occurrence in accepted:
            continue
        target = d.get("concrete_target") or c.get("target")
        if target in labels:
            label = labels[target][ru]
        elif (
            target is None and c["certainty"] == "unresolved" and c.get("semantic_subject") is None
        ):
            # This is already source-verified, unapplied evidence, not a new
            # target binding. Do not imply that a partial APPLIED accepted it.
            label = ("неразрешённый запрос" if ru else "unresolved request") + (
                " «" + c["evidence"]["text"] + "»"
            )
        else:
            continue
        reason = reasons.get(
            d["reason"],
            (
                "not accepted; review the unresolved request",
                "не принято; проверьте неразрешённый запрос",
            ),
        )[ru]
        details.append(label + " — " + reason)
    if not details:
        return original
    if payload["outcome"] == "NO_CHANGE":
        prefix = "Канонические значения не изменены. " if ru else "Canonical values are unchanged. "
    else:
        prefix = (
            "Поддерживаемые изменения сохранены. "
            if committed and ru
            else "Supported changes were saved. "
            if committed
            else "Изменение не сохранено. "
            if ru
            else "The change was not saved. "
        )
    return (
        prefix
        + ("Не применено из этого сообщения: " if ru else "Not applied from this message: ")
        + "; ".join(dict.fromkeys(details))
    )
