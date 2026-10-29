"""Pure canonical State traversal and complete locked-wrapper preservation.

No database currency, authorization, Knowledge policy or special-transition authority
is inferred here. Paths contain typed field segments and existing stable item IDs.
"""

from collections.abc import Iterable

from pydantic import BaseModel, TypeAdapter

from .models import Assumed, Derived, Explicit, KnownValue, NotApplicable, Unknown

FIELD_TYPES = (Unknown, NotApplicable, Explicit, Derived, Assumed)


def stable_item_id(item):
    for name in ("group_id", "component_id", "element_id"):
        value = getattr(item, name, None)
        if value is not None:
            return str(value)
    return None


def value_state_fields(value, prefix=()):
    if isinstance(value, BaseModel):
        return state_fields(value, prefix)
    result = {}
    if isinstance(value, tuple):
        for item in value:
            if isinstance(item, BaseModel):
                stable_id = stable_item_id(item)
                if stable_id is not None:
                    result.update(state_fields(item, (*prefix, stable_id)))
    return result


def state_fields(model, prefix=()):
    result = {}
    for name in type(model).model_fields:
        value = getattr(model, name)
        path = (*prefix, name)
        if value is None:
            result[path] = value
        elif isinstance(value, FIELD_TYPES):
            result[path] = value
            if isinstance(value, KnownValue):
                result.update(value_state_fields(value.value, path))
        else:
            result.update(value_state_fields(value, path))
    return result


def first_locked_change(before, after):
    """Return the first exact locked wrapper changed/removed, including metadata."""
    for path in sorted(before):
        old = before[path]
        if old is not None and old.locked and old != after.get(path):
            return path
    return None


def locked_ancestor(fields, target):
    for path in sorted(fields):
        state = fields[path]
        if state is not None and state.locked and target[: len(path)] == path:
            return path
    return None


def _state_annotation(design, target):
    current = design
    for index, segment in enumerate(target):
        if isinstance(current, KnownValue):
            current = current.value
        if isinstance(current, tuple):
            current = next(item for item in current if stable_item_id(item) == segment)
            continue
        field = type(current).model_fields[segment]
        if index == len(target) - 1:
            return field.annotation
        current = getattr(current, segment)
    raise ValueError("Canonical policy target is unavailable")


def _require_complete(value):
    if isinstance(value, BaseModel):
        if value.model_fields_set != set(type(value).model_fields):
            raise ValueError("Canonical policy aggregate requires a complete replacement")
        for name in type(value).model_fields:
            _require_complete(getattr(value, name))
    elif isinstance(value, tuple):
        for item in value:
            _require_complete(item)


def require_repeatable_replacement(value):
    """Reject non-snapshot iterables without iterating/consuming caller inputs.

    Only explicit dict/list/tuple containers and model fields are traversed;
    arbitrary iterables (including nested generators) are not replacement data.
    """
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            require_repeatable_replacement(getattr(value, name))
    elif type(value) is dict:
        for key, item in value.items():
            require_repeatable_replacement(key)
            require_repeatable_replacement(item)
    elif type(value) in (list, tuple):
        for item in value:
            require_repeatable_replacement(item)
    elif not isinstance(value, (str, bytes)) and (
        isinstance(value, Iterable) or hasattr(type(value), "__getitem__")
    ):
        # Python can also iterate legacy __getitem__ sequences that are not
        # registered with Iterable. Do not ask iter(value) to discover these.
        raise ValueError("Canonical policy requires a repeatable replacement snapshot")


def _validate_replacement_snapshot(design, target, checked):
    # Validate enclosing schema invariants too (e.g. stable collection ID
    # uniqueness), not just the generic State annotation in isolation.
    snapshot = design.model_dump(mode="json")
    cursor = snapshot
    for segment in target[:-1]:
        while isinstance(cursor, dict) and cursor.get("availability") == "value":
            cursor = cursor["value"]
        if isinstance(cursor, list):
            cursor = next(
                item
                for item in cursor
                if segment
                in (item.get("group_id"), item.get("component_id"), item.get("element_id"))
            )
        else:
            cursor = cursor[segment]
    while isinstance(cursor, dict) and cursor.get("availability") == "value":
        cursor = cursor["value"]
    cursor[target[-1]] = checked.model_dump(mode="json")
    type(design).model_validate(snapshot)


def validate_replacement_value(design, target, value, *, source):
    """Validate the existing target's type; partial aggregate JSON is not a patch."""
    try:
        # Validate through the actual generic State annotation (including PEP695
        # aliases). This temporary wrapper only checks value shape; it is never
        # persisted, returned as authority, or used to replace canonical sources.
        checked = TypeAdapter(_state_annotation(design, target)).validate_python(
            {
                "availability": "value",
                "origin": "explicit",
                "value": value,
                "source": source,
                "confirmed": False,
                "locked": False,
            }
        )
        validated = checked.value
        if value_state_fields(validated):
            _require_complete(validated)
        _validate_replacement_snapshot(design, target, checked)
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        # Do not echo proposed professional values or raw Pydantic payloads.
        raise ValueError("Canonical policy replacement is invalid or incomplete") from exc
    return validated
