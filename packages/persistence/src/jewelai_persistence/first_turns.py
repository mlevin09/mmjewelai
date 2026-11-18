"""Scoped immutable ST-01 retention in the existing initial transaction."""

from uuid import UUID

from jewelai_domain.clarification_state import evidence_hash

from .models import FirstConversationTurnRow, MessageRow
from .repository import EnrichmentIntegrityError, NotFoundError


def stage_first_turn(db, session, cycle, parent_id, payload, oid):
    binding = payload["binding"]
    message = db.get(MessageRow, UUID(binding["message_id"]))
    if (
        message is None
        or message.actor != "user"
        or message.session_id != session.session_id
        or binding["session_id"] != str(session.session_id)
        or binding["organization_id"] != str(oid)
        or binding["parent_revision_id"] != str(parent_id)
        or binding["result_revision_id"] != str(cycle.specification_revision_id)
        or binding["enrichment_cycle_id"] != str(cycle.enrichment_cycle_id)
        or binding["contract_version"] != cycle.source_contract
        or payload["content_hash"]
        != evidence_hash({k: v for k, v in payload.items() if k != "content_hash"})
    ):
        raise EnrichmentIntegrityError("First-turn source/receipt mismatch")
    db.add(
        FirstConversationTurnRow(
            session_id=session.session_id,
            organization_id=oid,
            message_id=message.message_id,
            parent_revision_id=parent_id,
            enrichment_cycle_id=cycle.enrichment_cycle_id,
            cycle_number=1,
            specification_revision_id=cycle.specification_revision_id,
            payload=payload,
            content_hash=payload["content_hash"],
        )
    )


def read_first_turn(repository, sid, oid):
    repository.get_design_session(sid, oid)
    with repository._session_factory() as db:
        row = db.get(FirstConversationTurnRow, sid)
        if row is None:
            raise NotFoundError("No first-turn receipt in session scope")
        binding = row.payload.get("binding", {})
        if (
            row.organization_id != oid
            or row.cycle_number != 1
            or binding.get("session_id") != str(sid)
            or binding.get("organization_id") != str(oid)
            or binding.get("message_id") != str(row.message_id)
            or binding.get("parent_revision_id") != str(row.parent_revision_id)
            or binding.get("result_revision_id") != str(row.specification_revision_id)
            or binding.get("enrichment_cycle_id") != str(row.enrichment_cycle_id)
            or row.content_hash != row.payload.get("content_hash")
            or row.content_hash
            != evidence_hash({k: v for k, v in row.payload.items() if k != "content_hash"})
        ):
            raise EnrichmentIntegrityError("Stored first-turn receipt binding mismatch")
        return row.payload
