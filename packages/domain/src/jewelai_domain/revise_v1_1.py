"""Safe parser-driven edit transition for Schema v1.1.

This transition is intentionally narrow: callers must pass a design produced by the
trusted Parser Proposal boundary. Generic user-supplied v1.1 edits remain disabled.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import AwareDatetime, TypeAdapter

from .models import MessageSource, RevisionEvent
from .models_v1_1 import DesignRevisionV1_1, DesignV1_1
from .revisions import RevisionConflict


def revise_parser_design_v1_1(
    current: DesignRevisionV1_1 | object,
    proposed: DesignV1_1 | object,
    *,
    expected_revision_id: UUID,
    source: MessageSource,
    reason: str,
    created_at: datetime,
) -> DesignRevisionV1_1:
    current = DesignRevisionV1_1.model_validate(current)
    proposed = DesignV1_1.model_validate(proposed)
    source = MessageSource.model_validate(source)
    created_at = TypeAdapter(AwareDatetime).validate_python(created_at)

    if current.revision_id != expected_revision_id:
        raise RevisionConflict("Stale revision: reload current state before editing")
    if current.design == proposed:
        raise RevisionConflict("No state change")
    if created_at < current.created_at:
        raise RevisionConflict("Revision timestamp cannot move backwards")

    return DesignRevisionV1_1(
        schema_version="1.1.0",
        design_id=current.design_id,
        revision_id=uuid4(),
        revision=current.revision + 1,
        parent_revision_id=current.revision_id,
        created_at=created_at,
        event=RevisionEvent(action="edit", source=source, reason=reason),
        design=proposed,
    )
