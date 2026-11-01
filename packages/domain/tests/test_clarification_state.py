"""Lossless F04 availability evidence without new canonical authority."""

from copy import deepcopy
from uuid import uuid4

import pytest
from test_canonical_lock_policy import current
from test_p0_21_knowledge_library_v1_1 import SOURCE, revision_v1_1

from jewelai_domain.clarification_state import (
    EvidenceScope,
    build_availability_overlay,
    evidence_hash,
    validate_availability_overlay,
)
from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import DesignRevisionV1_1


def scope(revision):
    return EvidenceScope(organization_id=uuid4(), session_id=uuid4(), design_id=revision.design_id)


@pytest.mark.parametrize("requirement", ("required", "optional", "undetermined"))
def test_unknown_qualifier_is_canonical_not_inferred_from_missing(requirement):
    data = revision_v1_1().model_dump(mode="json")
    data["design"]["metal"]["material"] = {"availability": "unknown", "requirement": requirement}
    revision = DesignRevisionV1_1.model_validate(data)
    s = scope(revision)
    before = revision.model_dump_json()
    overlay = build_availability_overlay(revision, scope=s)
    entry = next(e for e in overlay.entries if e.target.concrete_target == "metal.material")
    assert (entry.availability, entry.unknown_requirement, entry.not_applicable) == (
        "UNKNOWN",
        requirement,
        None,
    )
    assert revision.model_dump_json() == before
    assert validate_availability_overlay(overlay, revision, scope=s) == overlay
    # A checksum-valid lie must fail actual snapshot recomputation.
    forged = overlay.model_dump(mode="json")
    row = next(e for e in forged["entries"] if e["target"]["concrete_target"] == "metal.material")
    row["unknown_requirement"] = "optional" if requirement != "optional" else "required"
    forged["content_hash"] = evidence_hash({k: v for k, v in forged.items() if k != "content_hash"})
    with pytest.raises(ValueError, match="canonical revision"):
        validate_availability_overlay(forged, revision, scope=s)


def test_absence_and_not_applicable_are_separate_and_source_preserved():
    data = revision_v1_1().model_dump(mode="json")
    data["design"]["metal"]["material"] = None
    data["design"]["center_stone"]["cut"] = {
        "availability": "not_applicable",
        "reason": "Explicit synthetic test declaration",
        "source": SOURCE.model_dump(mode="json"),
        "confirmed": True,
        "locked": True,
    }
    revision = DesignRevisionV1_1.model_validate(data)
    overlay = build_availability_overlay(revision, scope=scope(revision))
    rows = {e.target.concrete_target: e for e in overlay.entries}
    assert rows["metal.material"].availability == "ABSENT"
    assert rows["metal.material"].origin is None
    cut = rows["center_stone.cut"]
    assert (cut.availability, cut.confirmed, cut.locked) == ("NOT_APPLICABLE", True, True)
    assert cut.not_applicable.source == SOURCE
    assert cut.not_applicable.reason == data["design"]["center_stone"]["cut"]["reason"]


@pytest.mark.parametrize("kind", ("composition", "component", "coating", "decorative"))
def test_nested_wrappers_use_real_pointers_and_stable_ids(kind):
    revision = current(kind)
    s = scope(revision)
    overlay = build_availability_overlay(revision, scope=s)
    payload = revision.model_dump(mode="json")
    for entry in overlay.entries:
        value = payload
        for token in entry.canonical_pointer.split("/")[1:]:
            key = token.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
        assert evidence_hash(value) == entry.canonical_state_sha256
    if kind in {"component", "coating"}:
        material = next(
            e
            for e in overlay.entries
            if e.target.concrete_target == "metal.components.shank.material"
        )
        assert material.target.owner_id == "shank"
    if kind == "decorative":
        assert any(e.target.owner_id == "ornament" for e in overlay.entries)
    assert validate_availability_overlay(overlay, revision, scope=s) == overlay


def test_unavailable_aggregate_does_not_fabricate_descendant_unknowns():
    data = revision_v1_1().model_dump(mode="json")
    data["design"]["composition"] = {"availability": "unknown", "requirement": "required"}
    revision = DesignRevisionV1_1.model_validate(data)
    rows = build_availability_overlay(revision, scope=scope(revision)).entries
    assert any(
        e.target.concrete_target == "composition" and e.unknown_requirement == "required"
        for e in rows
    )
    assert not any(e.target.concrete_target.startswith("composition.") for e in rows)


def test_stale_or_foreign_overlay_fails_without_modifying_revision():
    revision = revision_v1_1()
    s = scope(revision)
    overlay = build_availability_overlay(revision, scope=s)
    with pytest.raises(ValueError, match="canonical revision"):
        validate_availability_overlay(overlay, revision, scope=scope(revision))
    data = revision.model_dump(mode="json")
    data["revision_id"] = str(uuid4())
    changed = DesignRevisionV1_1.model_validate(data)
    with pytest.raises(ValueError, match="canonical revision"):
        validate_availability_overlay(overlay, changed, scope=s)


def test_original_v1_schema_supported_without_snapshot_upgrade():
    data = deepcopy(revision_v1_1().model_dump(mode="json"))
    data["schema_version"] = "1.0.0"
    # The base fixture has no populated v1.1-only canonical facts.
    from jewelai_domain.models import Design

    data["design"] = Design().model_dump(mode="json")
    revision = DesignRevision.model_validate(data)
    overlay = build_availability_overlay(revision, scope=scope(revision))
    assert overlay.design_schema_version == "1.0.0"
    assert all(e.target.group_id is None for e in overlay.entries)
