"""Pure revision transitions; persistence must additionally use atomic compare-and-swap."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, TypeAdapter

from .models import (
    Assumed,
    Derived,
    Design,
    DesignRevision,
    Explicit,
    MessageSource,
    NotApplicable,
    RevisionEvent,
    Unknown,
)

FIELD_TYPES = (Unknown, NotApplicable, Explicit, Derived, Assumed)


class RevisionConflict(ValueError):
    """The caller's revision is stale or an edit violates a state transition."""


def _fields(model, prefix=()):
    result = {}
    for name in type(model).model_fields:
        value = getattr(model, name)
        path = (*prefix, name)
        if value is None or isinstance(value, FIELD_TYPES):
            result[path] = value
        elif name == "side_stones":
            for group in value:
                result.update(_fields(group.stones, (*path, group.group_id, "stones")))
                result[(*path, group.group_id, "quantity")] = group.quantity
        elif isinstance(value, BaseModel):
            result.update(_fields(value, path))
    return result


def _check_current(current, expected_revision_id):
    current = DesignRevision.model_validate(current)
    if current.revision_id != expected_revision_id:
        raise RevisionConflict("Stale revision: reload current state before editing")
    return current


def _new_revision(current, design, source, reason, action, created_at):
    created_at = TypeAdapter(AwareDatetime).validate_python(created_at)
    if created_at < current.created_at:
        raise RevisionConflict("Revision timestamp cannot move backwards")
    return DesignRevision(
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
    current: DesignRevision,
    proposed: Design,
    *,
    expected_revision_id: UUID,
    source: MessageSource,
    reason: str,
    created_at: datetime,
) -> DesignRevision:
    """Apply an unconfirmed proposal while retaining every locked leaf, including deletions."""
    current = _check_current(current, expected_revision_id)
    proposed = Design.model_validate(proposed)
    before, after = _fields(current.design), _fields(proposed)
    if current.design == proposed:
        raise RevisionConflict("No state change")
    # Check existing locks first and in stable order, including removed group IDs.
    for path in sorted(before):
        old = before[path]
        if old is not None and old.locked and old != after.get(path):
            raise RevisionConflict(f"Locked field: {'.'.join(path)}")
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
        if isinstance(cursor, list):
            cursor = next(group for group in cursor if group["group_id"] == part)
        else:
            cursor = cursor[part]
    leaf = cursor[key[-1]]
    if action == "confirm":
        leaf["confirmed"] = True
    else:
        leaf["locked"] = action == "lock"
    return _new_revision(current, Design.model_validate(data), source, reason, action, created_at)


def confirm_field(
    current: DesignRevision,
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
    current: DesignRevision,
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
    current: DesignRevision,
    path: str,
    *,
    expected_revision_id: UUID,
    source: MessageSource,
    reason: str,
    created_at: datetime,
) -> DesignRevision:
    """Record explicit unlock intent; changing the value later requires reconfirmation."""
    return _transition(current, path, expected_revision_id, source, reason, created_at, "unlock")
