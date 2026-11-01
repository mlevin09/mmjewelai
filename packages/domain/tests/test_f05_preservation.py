"""Approved F05 scope and one-shot release invariants; no provider dependency."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import DesignRevisionV1_1
from jewelai_domain.preservation import (
    RELEASE_TARGETS,
    PreservationConflict,
    anchor_hash,
    build_preservation_root,
    check_preservation_transition,
    protected_targets,
    validate_scoped_release,
)
from jewelai_domain.revisions import revise_design


def revision():
    source = MessageSource(message_id=str(uuid4()), recorded_at=datetime(2026, 11, 1, tzinfo=UTC))

    def explicit(value):
        return dict(
            availability="value",
            origin="explicit",
            value=value,
            source=source.model_dump(mode="json"),
            confirmed=False,
            locked=False,
        )

    return DesignRevisionV1_1(
        design_id=uuid4(),
        revision_id=uuid4(),
        revision=1,
        created_at=source.recorded_at,
        parent_revision_id=None,
        event=dict(action="create", source=source, reason="Explicit synthetic canonical fixture"),
        design=dict(
            center_stone=dict(
                shape=explicit("oval"), material_origin_status=explicit("synthetic_fixture")
            )
        ),
    )


def root(rev, field=None):
    return build_preservation_root(
        evidence_id="constraint_" + "a" * 24,
        evidence_hash="b" * 64,
        source_revision=rev,
        source_cycle_id=uuid4(),
        field=field,
    )


def test_schema_complete_scope_separate_from_release_targets():
    assert len(protected_targets("1.0.0")) == 8
    assert len(protected_targets("1.1.0")) == 14
    assert len(RELEASE_TARGETS) == 6
    assert "center_stone.material_origin_status" in protected_targets("1.1.0")
    assert "center_stone.material_origin_status" not in RELEASE_TARGETS
    with pytest.raises(ValueError):
        protected_targets("1.2.0")


def test_generic_keep_blocks_actual_delta_but_preserves_unrelated_field():
    old = revision()
    design = deepcopy(old.design)
    design = design.model_copy(
        update={
            "center_stone": design.center_stone.model_copy(
                update={
                    "shape": design.center_stone.shape.model_copy(update={"value": "emerald_cut"})
                }
            )
        }
    )
    with pytest.raises(PreservationConflict):
        check_preservation_transition(old, design, (root(old),))
    assert anchor_hash(old.design.center_stone.material_origin_status)


def test_missing_and_all_additive_fields_are_protected():
    old = revision()
    for target in protected_targets("1.1.0"):
        design = deepcopy(old.design)
        field = target.split(".")[1]
        current = getattr(design.center_stone, field)
        design = design.model_copy(
            update={
                "center_stone": design.center_stone.model_copy(
                    update={field: None if current is not None else old.design.center_stone.shape}
                )
            }
        )
        with pytest.raises(PreservationConflict):
            check_preservation_transition(old, design, (root(old),))


def test_shape_specific_keep_does_not_expand_to_other_fields():
    old = revision()
    specific = root(old, field="shape")
    assert specific.scope_targets == ("center_stone.shape",)
    design = deepcopy(old.design)
    design = design.model_copy(
        update={
            "center_stone": design.center_stone.model_copy(update={"material_origin_status": None})
        }
    )
    check_preservation_transition(old, design, (specific,))


def test_release_reanchors_one_field_under_every_root_without_mutating_history():
    old = revision()
    generic = root(old)
    specific = build_preservation_root(
        evidence_id="constraint_" + "c" * 24,
        evidence_hash="d" * 64,
        source_revision=old,
        source_cycle_id=uuid4(),
        field="shape",
    )
    roots = (generic, specific)
    original_bytes = tuple(r.model_dump_json() for r in roots)
    authorization = MessageSource(message_id=str(uuid4()), recorded_at=old.created_at)
    design = old.design.model_dump(mode="json")
    design["center_stone"]["shape"]["value"] = "emerald_cut"
    after = revise_design(
        old,
        design,
        expected_revision_id=old.revision_id,
        source=authorization,
        reason="Exact typed release fixture",
        created_at=old.created_at,
    )
    refs = [(r.evidence_id, r.evidence_hash) for r in roots]
    actual = validate_scoped_release(
        old,
        after,
        roots,
        target="center_stone.shape",
        root_refs=refs,
        authorization_source=authorization,
    )
    assert actual == anchor_hash(after.design.center_stone.shape)
    assert (
        after.design.center_stone.material_origin_status
        == old.design.center_stone.material_origin_status
    )
    assert tuple(r.model_dump_json() for r in roots) == original_bytes
    with pytest.raises(PreservationConflict):
        validate_scoped_release(
            old,
            after,
            roots,
            target="center_stone.shape",
            root_refs=refs[:1],
            authorization_source=authorization,
        )
    # A valid prior authorization is not permission for another transition.
    with pytest.raises(PreservationConflict):
        check_preservation_transition(after, old.design, roots)


def test_hash_valid_root_cannot_omit_a_declared_scope_anchor():
    old = revision()
    original = root(old)
    payload = original.model_dump(mode="json")
    payload["original_anchors"] = payload["original_anchors"][:-1]
    from jewelai_domain.preservation import PreservationRoot, contract_hash

    payload["content_hash"] = contract_hash(
        "jewelai.PreservationRoot/1.0.0", {k: v for k, v in payload.items() if k != "content_hash"}
    )
    with pytest.raises(ValueError, match="scope"):
        PreservationRoot.model_validate(payload)
