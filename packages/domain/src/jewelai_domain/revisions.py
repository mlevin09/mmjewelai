"""Pure revision transitions; persistence must additionally use atomic compare-and-swap."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import AwareDatetime, TypeAdapter

from .lock_protection import first_locked_change, state_fields
from .models import (
    Design,
    DesignRevision,
    MessageSource,
    NotApplicable,
    RevisionEvent,
    Unknown,
)
from .models_v1_1 import (
    AnyDesignRevision,
    DesignRevisionV1_1,
    DesignV1_1,
    validate_design_revision,
)


class RevisionConflict(ValueError):
    """The caller's revision is stale or an edit violates a state transition."""


_fields = state_fields  # Retain the internal traversal alias for existing consumers.


def _check_current(current, expected_revision_id):
    current = validate_design_revision(current)
    if current.revision_id != expected_revision_id:
        raise RevisionConflict("Stale revision: reload current state before editing")
    return current


def _new_revision(current, design, source, reason, action, created_at):
    created_at = TypeAdapter(AwareDatetime).validate_python(created_at)
    if created_at < current.created_at:
        raise RevisionConflict("Revision timestamp cannot move backwards")
    revision_type = (
        DesignRevisionV1_1 if isinstance(current, DesignRevisionV1_1) else DesignRevision
    )
    return revision_type(
        schema_version=current.schema_version,
        design_id=current.design_id,
        revision_id=uuid4(),
        revision=current.revision + 1,
        parent_revision_id=current.revision_id,
        created_at=created_at,
        event=RevisionEvent(action=action, source=source, reason=reason),
        design=design,
    )


def revise_design(
    current: AnyDesignRevision | object,
    proposed: Design | DesignV1_1 | object,
    *,
    expected_revision_id: UUID,
    source: MessageSource,
    reason: str,
    created_at: datetime,
) -> DesignRevision:
    """Apply an unconfirmed proposal while retaining every locked leaf, including deletions."""
    current = _check_current(current, expected_revision_id)
    proposed = (
        DesignV1_1.model_validate(proposed)
        if isinstance(current, DesignRevisionV1_1)
        else Design.model_validate(proposed)
    )
    before, after = _fields(current.design), _fields(proposed)
    if current.design == proposed:
        raise RevisionConflict("No state change")
    # Check existing locks first and in stable order, including removed group IDs.
    locked_change = first_locked_change(before, after)
    if locked_change is not None:
        raise RevisionConflict(f"Locked field: {'.'.join(locked_change)}")
    for path in sorted(before.keys() | after.keys()):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if new is not None and new.locked:
            raise RevisionConflict("Use lock_field after confirmation")
        if new is not None and new.confirmed:
            # A declaration of inapplicability is explicit and already sourced.
            if not isinstance(new, NotApplicable):
                raise RevisionConflict("Changed values must be unconfirmed; use confirm_field")
    return _new_revision(current, proposed, source, reason, "edit", created_at)


def _transition(current, path, expected_revision_id, source, reason, created_at, action):
    current = _check_current(current, expected_revision_id)
    key = tuple(path.split("."))
    fields = _fields(current.design)
    if key not in fields or fields[key] is None or isinstance(fields[key], Unknown):
        raise RevisionConflict("Transition requires a known or explicitly inapplicable field")
    value = fields[key]
    if action == "confirm" and (value.confirmed or value.locked):
        raise RevisionConflict("Field is already confirmed")
    if action == "lock" and (not value.confirmed or value.locked):
        raise RevisionConflict("Only a confirmed, unlocked field can be locked")
    if action == "unlock" and not value.locked:
        raise RevisionConflict("Field is not locked")
    data = current.design.model_dump(mode="json")
    cursor = data
    for part in key[:-1]:
        while (
            isinstance(cursor, dict)
            and cursor.get("availability") == "value"
            and isinstance(cursor.get("value"), (dict, list))
        ):
            cursor = cursor["value"]
        if isinstance(cursor, list):
            cursor = next(
                item
                for item in cursor
                if any(
                    item.get(id_key) == part
                    for id_key in ("group_id", "component_id", "element_id")
                )
            )
        else:
            cursor = cursor[part]
    while (
        isinstance(cursor, dict)
        and cursor.get("availability") == "value"
        and isinstance(cursor.get("value"), (dict, list))
    ):
        cursor = cursor["value"]
    leaf = cursor[key[-1]]
    if action == "confirm":
        leaf["confirmed"] = True
    else:
        leaf["locked"] = action == "lock"
    design_type = DesignV1_1 if isinstance(current, DesignRevisionV1_1) else Design
    return _new_revision(
        current,
        design_type.model_validate(data),
        source,
        reason,
        action,
        created_at,
    )


def confirm_field(
    current: AnyDesignRevision | object,
    path: str,
    *,
    expected_revision_id: UUID,
    source: MessageSource,
    reason: str,
    created_at: datetime,
) -> DesignRevision:
    """Confirm the current value without changing its provenance."""
    return _transition(current, path, expected_revision_id, source, reason, created_at, "confirm")


def lock_field(
    current: AnyDesignRevision | object,
    path: str,
    *,
    expected_revision_id: UUID,
    source: MessageSource,
    reason: str,
    created_at: datetime,
) -> DesignRevision:
    """Lock a confirmed field; collection paths use stable side-stone group IDs."""
    return _transition(current, path, expected_revision_id, source, reason, created_at, "lock")


def unlock_field(
    current: AnyDesignRevision | object,
    path: str,
    *,
    expected_revision_id: UUID,
    source: MessageSource,
    reason: str,
    created_at: datetime,
) -> DesignRevision:
    """Record explicit unlock intent; changing the value later requires reconfirmation."""
    return _transition(current, path, expected_revision_id, source, reason, created_at, "unlock")
