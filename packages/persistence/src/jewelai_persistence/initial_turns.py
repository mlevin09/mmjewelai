"""Existing repository transactions for the scoped US-01 first-turn contract."""

from copy import deepcopy
from uuid import UUID

from jewelai_domain.clarification_state import evidence_hash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import (
    EnrichmentCycleRow,
    FirstConversationTurnRow,
    InitialConversationTurnRow,
)
from .repository import (
    EnrichmentIntegrityError,
    NotFoundError,
    OwnershipMismatchError,
    StaleRevisionError,
)


def _verified(row, sid, oid):
    p = row.input_payload
    if (
        row.session_id != sid
        or row.organization_id != oid
        or p["session_id"] != str(sid)
        or p["organization_id"] != str(oid)
        or p["message_id"] != str(row.message_id)
        or p["request"]["turn_id"] != str(row.turn_id)
        or p["request"]["expected_revision_id"] != str(row.parent_revision_id)
        or p["result_revision_id"] != str(row.result_revision_id)
        or p["design_id"] != str(row.design_id)
        or row.input_hash != evidence_hash(p)
        or (row.reply_payload is None) != (row.reply_hash is None)
        or row.reply_payload is not None
        and row.reply_hash != evidence_hash(row.reply_payload)
    ):
        raise EnrichmentIntegrityError("Initial conversation source or delivery mismatch")
    return {
        "input": deepcopy(p),
        "input_hash": row.input_hash,
        "reply": deepcopy(row.reply_payload),
        "reply_hash": row.reply_hash,
    }


def read(repository, sid, oid):
    repository.get_design_session(sid, oid)
    with repository._session_factory() as db:
        row = db.get(InitialConversationTurnRow, sid)
        if row is None:
            raise NotFoundError("No US-01 first turn in session scope")
        return _verified(row, sid, oid)


def commit(repository, *, sid, oid, expected_revision_id, revision, message, payload, verify):
    try:
        with repository._session_factory.begin() as db:
            session = db.scalar(repository._scoped_session_query(sid, oid).with_for_update())
            if session is None:
                raise OwnershipMismatchError("Session not found in organization scope")
            retained = db.get(InitialConversationTurnRow, sid)
            if retained is not None:
                record = _verified(retained, sid, oid)
                if record["input"]["request"] == payload["request"]:
                    return False  # Same turn won the race; never append State/source twice.
                raise StaleRevisionError("Another first turn already committed")
            repository._require_native_workflow(db, sid)
            if (session.question_artifact_version, session.rules_artifact_version) != (
                "2.0.0",
                "2.0.0",
            ):
                raise ValueError("US-01 requires retained F artifacts")
            if session.current_revision_id != expected_revision_id:
                raise StaleRevisionError("Product State changed before first-turn commit")
            if (
                session.knowledge_package_id is not None
                or db.get(FirstConversationTurnRow, sid) is not None
                or db.scalar(
                    select(EnrichmentCycleRow.enrichment_cycle_id)
                    .where(EnrichmentCycleRow.session_id == sid)
                    .limit(1)
                )
            ):
                raise StaleRevisionError("US-01 is only available before the first enrichment turn")
            parent = repository._locked_revision(db, sid, expected_revision_id)
            if (
                message.session_id != sid
                or message.actor != "user"
                or message.content != payload["request"]["original_text"]
            ):
                raise EnrichmentIntegrityError("Initial Message must equal the actual raw input")
            db.add(message)
            db.flush()
            if revision.revision_id != expected_revision_id:
                repository._validate_next_revision(parent, revision)
                db.add(repository._revision_row(sid, revision))
                db.flush()
                session.current_revision_id = revision.revision_id
            session.updated_at = message.created_at
            row = InitialConversationTurnRow(
                session_id=sid,
                organization_id=oid,
                turn_id=UUID(payload["request"]["turn_id"]),
                message_id=message.message_id,
                design_id=revision.design_id,
                parent_revision_id=expected_revision_id,
                result_revision_id=revision.revision_id,
                input_payload=payload,
                input_hash=evidence_hash(payload),
                reply_payload=None,
                reply_hash=None,
                created_at=message.created_at,
            )
            db.add(row)
            db.flush()
            _verified(row, sid, oid)
            from .preparations import locked_reader

            verify(locked_reader(db))
        return True
    except IntegrityError:
        raise StaleRevisionError("First turn or source identity already committed") from None


def deliver(repository, *, sid, oid, input_hash, reply, verify):
    with repository._session_factory.begin() as db:
        session = db.scalar(repository._scoped_session_query(sid, oid).with_for_update())
        if session is None:
            raise OwnershipMismatchError("Session not found in organization scope")
        row = db.get(InitialConversationTurnRow, sid)
        if row is None:
            raise NotFoundError("Committed first turn is missing")
        record = _verified(row, sid, oid)
        if (
            record["input_hash"] != input_hash
            or reply["input_hash"] != input_hash
            or reply["revision_id"] != str(row.result_revision_id)
        ):
            raise EnrichmentIntegrityError("Delivery context does not match committed input")
        if session.current_revision_id != row.result_revision_id or row.reply_payload is not None:
            raise StaleRevisionError("First-turn delivery is stale or already saved")
        row.reply_payload = reply
        row.reply_hash = evidence_hash(reply)
        db.flush()
        from .preparations import locked_reader

        verify(locked_reader(db))
