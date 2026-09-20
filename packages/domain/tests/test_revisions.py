import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from jewelai_domain import (
    Design,
    DesignRevision,
    RevisionConflict,
    confirm_field,
    lock_field,
    revise_design,
    unlock_field,
)
from jewelai_domain.models import MessageSource

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "jewelry-design-schema"
    / "fixtures"
    / "valid"
    / "ring.json"
)
NOW = datetime(2026, 9, 21, tzinfo=UTC)
SOURCE = MessageSource(message_id="user-change", recorded_at=NOW)


@pytest.fixture
def current():
    return DesignRevision.model_validate_json(FIXTURE.read_text())


def args(current):
    return dict(
        expected_revision_id=current.revision_id,
        source=SOURCE,
        reason="Explicit user operation",
        created_at=NOW,
    )


def changed(current, section, field, value):
    data = current.design.model_dump(mode="json")
    data[section][field] = value
    return Design.model_validate(data)


def explicit(value, confirmed=False, locked=False):
    return {
        "origin": "explicit",
        "value": value,
        "source": SOURCE.model_dump(mode="json"),
        "confirmed": confirmed,
        "locked": locked,
    }


def test_immutable_unlock_edit_confirm_lock_flow(current):
    original = current.model_dump_json()
    unlocked = unlock_field(current, "metal.color", **args(current))
    assert unlocked.design.metal.color.confirmed
    proposal = changed(unlocked, "metal", "color", explicit("yellow"))
    edited = revise_design(unlocked, proposal, **args(unlocked))
    assert not edited.design.metal.color.confirmed
    confirmed = confirm_field(edited, "metal.color", **args(edited))
    locked = lock_field(confirmed, "metal.color", **args(confirmed))
    assert locked.design.metal.color.locked
    assert locked.design.metal.color.value == "yellow"
    assert locked.design.metal.color.source == SOURCE
    assert current.model_dump_json() == original
    revisions = [current, unlocked, edited, confirmed, locked]
    assert [r.revision for r in revisions] == [1, 2, 3, 4, 5]
    assert len({r.revision_id for r in revisions}) == 5
    for parent, child in zip(revisions[:-1], revisions[1:], strict=True):
        assert child.parent_revision_id == parent.revision_id
        assert child.design_id == parent.design_id
        assert child.event.source == SOURCE


@pytest.mark.parametrize("operation", ["change", "remove", "silent_unlock", "source_change"])
def test_locked_field_cannot_be_bypassed(current, operation):
    data = current.design.model_dump(mode="json")
    if operation == "change":
        data["metal"]["color"] = explicit("yellow")
    elif operation == "remove":
        data["metal"] = {}
    elif operation == "silent_unlock":
        data["metal"]["color"]["locked"] = False
    else:
        data["metal"]["color"]["source"]["message_id"] = "different"
    with pytest.raises(RevisionConflict, match="Locked field"):
        revise_design(current, Design.model_validate(data), **args(current))


def test_removing_or_renaming_side_group_does_not_drop_a_lock(current):
    locked = lock_field(current, "side_stones.accents.quantity", **args(current))
    for groups in (
        [],
        [dict(locked.design.model_dump(mode="json")["side_stones"][0], group_id="renamed")],
    ):
        data = locked.design.model_dump(mode="json")
        data["side_stones"] = groups
        with pytest.raises(RevisionConflict, match="Locked field"):
            revise_design(locked, Design.model_validate(data), **args(locked))


@pytest.mark.parametrize("operation", [confirm_field, lock_field, unlock_field])
def test_all_transitions_reject_stale_revision(current, operation):
    options = args(current)
    options["expected_revision_id"] = uuid4()
    with pytest.raises(RevisionConflict, match="Stale"):
        operation(current, "metal.color", **options)


def test_edit_rejects_stale_revision(current):
    options = args(current)
    options["expected_revision_id"] = uuid4()
    with pytest.raises(RevisionConflict, match="Stale"):
        revise_design(current, current.design, **options)


@pytest.mark.parametrize("path", ["missing.field", "metal.finish", "center_stone.dimensions"])
@pytest.mark.parametrize("operation", [confirm_field, lock_field, unlock_field])
def test_unknown_absent_and_invalid_path_cannot_transition(current, path, operation):
    with pytest.raises(RevisionConflict):
        operation(current, path, **args(current))


def test_changed_value_cannot_carry_confirmation_or_lock(current):
    for confirmed, locked in [(True, False), (True, True)]:
        proposal = changed(current, "center_stone", "shape", explicit("pear", confirmed, locked))
        with pytest.raises(RevisionConflict):
            revise_design(current, proposal, **args(current))


def test_unconfirmed_value_cannot_be_locked(current):
    proposal = changed(current, "center_stone", "shape", explicit("pear"))
    edited = revise_design(current, proposal, **args(current))
    with pytest.raises(RevisionConflict, match="confirmed"):
        lock_field(edited, "center_stone.shape", **args(edited))


def test_noop_and_backdated_revision_rejected(current):
    with pytest.raises(RevisionConflict, match="No state change"):
        revise_design(current, current.design, **args(current))
    options = args(current)
    options["created_at"] = current.created_at - timedelta(seconds=1)
    with pytest.raises(RevisionConflict, match="backwards"):
        unlock_field(current, "metal.color", **options)


def test_explicit_not_applicable_is_audited_and_lockable(current):
    proposal = changed(
        current,
        "construction",
        "clasp",
        {
            "availability": "not_applicable",
            "reason": "A ring has no clasp",
            "source": SOURCE.model_dump(mode="json"),
        },
    )
    edited = revise_design(current, proposal, **args(current))
    locked = lock_field(edited, "construction.clasp", **args(edited))
    assert locked.design.construction.clasp.locked
    with pytest.raises(RevisionConflict):
        revise_design(locked, current.design, **args(locked))


def test_wire_serialization_does_not_expose_mutable_state(current):
    data = json.loads(current.model_dump_json())
    data["design"]["metal"]["color"]["value"] = "changed"
    assert current.design.metal.color.value == "white"


def test_confirming_derived_value_preserves_origin_and_sources():
    current = DesignRevision.model_validate_json(
        (FIXTURE.parent / "derived-dimensions.json").read_text()
    )
    before = current.design.center_stone.dimensions
    confirmed = confirm_field(current, "center_stone.dimensions", **args(current))
    after = confirmed.design.center_stone.dimensions
    assert after.confirmed and after.origin == "derived"
    assert after.sources == before.sources
    assert after.uncertainty == before.uncertainty


def test_reordering_groups_uses_stable_ids(current):
    locked = lock_field(current, "side_stones.accents.quantity", **args(current))
    data = locked.design.model_dump(mode="json")
    data["side_stones"].insert(0, {"group_id": "other", "stones": {}})
    reordered = revise_design(locked, Design.model_validate(data), **args(locked))
    assert reordered.design.side_stones[1].quantity.locked
    unlocked = unlock_field(reordered, "side_stones.accents.quantity", **args(reordered))
    assert not unlocked.design.side_stones[1].quantity.locked
