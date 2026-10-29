"""LCK-001..016 canonical authority and complete locked-wrapper regressions."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_p0_21_knowledge_library_v1_1 import NOW, SOURCE, bundle_v1_1, revision_v1_1

from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary
from jewelai_domain.knowledge_library_v1_1 import compile_knowledge_library_v1_1
from jewelai_domain.knowledge_policy import (
    CANONICAL_POLICY_EVALUATION_VERSION,
    KnowledgePolicyEngine,
    KnowledgeRuntimeState,
    PreservationIntent,
    RuntimeProvenance,
    RuntimeSemanticState,
    RuntimeStateProposal,
    build_knowledge_runtime_state,
)
from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import DesignRevisionV1_1, DesignV1_1
from jewelai_domain.revisions import (
    RevisionConflict,
    confirm_field,
    lock_field,
    revise_design,
    unlock_field,
)


@pytest.fixture
def engine():
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1())
    return KnowledgePolicyEngine(runtime)


def explicit(value, locked=False):
    return dict(
        availability="value",
        origin="explicit",
        value=value,
        source=SOURCE.model_dump(mode="json"),
        confirmed=locked,
        locked=locked,
    )


def current(kind="composition", parent=False):
    data = revision_v1_1().model_dump(mode="json")
    if kind == "composition":
        data["design"]["composition"] = explicit(
            {
                "symmetry_mode": explicit("asymmetrical", not parent),
                "rhythm": explicit("regular"),
            },
            parent,
        )
    elif kind in {"component", "coating"}:
        component = {"component_id": "shank", "material": explicit("platinum", kind == "component")}
        if kind == "coating":
            component["coating"] = explicit({"material": explicit("rhodium", True)})
        data["design"]["metal"]["components"] = explicit([component])
    elif kind == "decorative":
        data["design"]["decorative_elements"] = explicit(
            [{"element_id": "ornament", "motif": explicit("floral", True)}]
        )
    return DesignRevisionV1_1.model_validate(data)


def proposal(target, value, **kwargs):
    return RuntimeStateProposal(
        target=target,
        value=value,
        semantic_state=kwargs.pop("semantic_state", RuntimeSemanticState.EXPLICIT),
        provenance=kwargs.pop("provenance", RuntimeProvenance.USER_EXPLICIT_LATEST),
        source_id=kwargs.pop("source_id", "LCK-user"),
        **kwargs,
    )


def evaluate(engine, revision, proposed, **kwargs):
    return engine.evaluate_canonical(
        revision, proposed, expected_revision_id=revision.revision_id, **kwargs
    )


def edit_args(revision):
    return dict(
        expected_revision_id=revision.revision_id,
        source=SOURCE,
        reason="LCK synthetic regression",
        created_at=NOW,
    )


def aggregate(design, kind):
    if kind in {"component", "coating"}:
        return "metal.components", design["metal"]["components"]
    target = "composition" if kind == "composition" else "decorative_elements"
    return target, design[target]


@pytest.mark.parametrize("same", [False, True], ids=["LCK-001-change", "LCK-001-same"])
def test_parent_lock_blocks_child_even_same_value(engine, same):
    revision = current(parent=True)
    result = evaluate(
        engine,
        revision,
        proposal("composition.symmetry_mode", "asymmetrical" if same else "radial"),
    )
    assert (result.outcome, result.reason) == ("BLOCKED", "locked")
    assert not result.current.locked


@pytest.mark.parametrize("value", [None, {}, {"symmetry_mode": None}])
def test_parent_lock_blocks_reset_and_nested_addition(engine, value):
    revision = current(parent=True)
    for item in [proposal("composition", value), proposal("composition.organization", "linear")]:
        assert evaluate(engine, revision, item).reason == "locked"


@pytest.mark.parametrize(
    "kind,mutation",
    [
        ("composition", "change"),
        ("composition", "source"),
        ("component", "remove"),
        ("component", "rekey"),
        ("decorative", "remove"),
        ("decorative", "rekey"),
        ("coating", "change"),
        ("coating", "source"),
        ("coating", "unlock"),
    ],
)
def test_complete_aggregate_lock_parity(engine, kind, mutation):
    revision = current(kind)
    before = revision.model_dump_json()
    data = revision.design.model_dump(mode="json")
    target, item = aggregate(data, kind)
    if kind == "composition":
        child = item["value"]["symmetry_mode"]
    elif kind == "decorative":
        child = item["value"][0]["motif"]
    elif kind == "component":
        child = item["value"][0]["material"]
    else:
        child = item["value"][0]["coating"]["value"]["material"]
    if mutation == "remove":
        item["value"] = []
    elif mutation == "rekey":
        item["value"][0]["element_id" if kind == "decorative" else "component_id"] = "renamed"
    elif mutation == "source":
        child["source"]["message_id"] = "different-source"
    elif mutation == "unlock":
        child["locked"] = False
    else:
        child.update(value="changed", confirmed=False, locked=False)
    design = DesignV1_1.model_validate(data)
    _, full = aggregate(design.model_dump(mode="json"), kind)
    result = evaluate(engine, revision, proposal(target, full["value"]))
    assert (result.outcome, result.reason) == ("BLOCKED", "locked")
    with pytest.raises(RevisionConflict, match="Locked field"):
        revise_design(revision, design, **edit_args(revision))
    assert revision.model_dump_json() == before


def test_unlocked_sibling_and_exact_segments(engine):
    revision = current("component")
    data = revision.design.model_dump(mode="json")
    data["metal"]["components"]["value"][0]["finish"] = explicit("matte")
    data["metal"]["components"]["value"].append(
        {"component_id": "shank_extra", "material": explicit("gold")}
    )
    design = DesignV1_1.model_validate(data)
    value = design.model_dump(mode="json")["metal"]["components"]["value"]
    assert evaluate(engine, revision, proposal("metal.components", value)).outcome == "APPLIED"
    updated = revise_design(revision, design, **edit_args(revision))
    assert updated.design.metal.components.value[0].material.locked
    assert (
        evaluate(
            engine, updated, proposal("metal.components.shank_extra.material", "silver")
        ).outcome
        == "APPLIED"
    )


def test_special_transitions_do_not_cascade(engine):
    revision = current(parent=True)
    confirmed = confirm_field(revision, "composition.symmetry_mode", **edit_args(revision))
    locked = lock_field(confirmed, "composition.symmetry_mode", **edit_args(confirmed))
    unlocked = unlock_field(locked, "composition", **edit_args(locked))
    assert not unlocked.design.composition.locked
    assert unlocked.design.composition.value.symmetry_mode.locked
    assert (
        evaluate(engine, unlocked, proposal("composition.symmetry_mode", "radial")).reason
        == "locked"
    )


@pytest.mark.parametrize("knowledge", [False, True], ids=["LCK-009", "LCK-010"])
def test_provenance_cannot_bypass_parent(engine, knowledge):
    change = proposal(
        "composition.symmetry_mode",
        "radial",
        semantic_state=RuntimeSemanticState.RECOMMENDED
        if knowledge
        else RuntimeSemanticState.EXPLICIT,
        provenance=RuntimeProvenance.KNOWLEDGE_INFERRED
        if knowledge
        else RuntimeProvenance.USER_CONFIRMED,
        source_id="DEC-P0-21" if knowledge else "user",
    )
    assert evaluate(engine, current(parent=True), change).reason == "locked"


@pytest.mark.parametrize("attack", ["forged", "stale", "incomplete", "release", "revision"])
def test_untrusted_effective_state_is_not_lock_authority(engine, attack):
    revision = current(parent=True)
    data = build_knowledge_runtime_state(engine.runtime, revision).model_dump(mode="json")
    if attack == "forged":
        next(item for item in data["parameters"] if item["target"] == "composition")["locked"] = (
            False
        )
    elif attack == "incomplete":
        data["parameters"] = [
            item for item in data["parameters"] if item["target"] == "composition.symmetry_mode"
        ]
    elif attack == "release":
        data["runtime_sha256"] = "0" * 64
    state = (
        build_knowledge_runtime_state(engine.runtime, revision_v1_1())
        if attack == "stale"
        else KnowledgeRuntimeState.model_validate(data)
    )
    change = proposal("composition.symmetry_mode", "radial")
    if attack in {"incomplete", "release", "revision"}:
        with pytest.raises(ValueError, match="context|identity"):
            engine.evaluate_canonical(
                revision,
                change,
                expected_revision_id=uuid4() if attack == "revision" else revision.revision_id,
                effective_state=state,
            )
    else:
        assert evaluate(engine, revision, change, effective_state=state).reason == "locked"
    with pytest.raises(ValueError, match="canonical v2"):
        engine.evaluate(state, change)


def test_legacy_runtime_is_not_an_expanded_flat_bypass():
    runtime = CompiledKnowledgeLibrary(
        package_id="test.legacy",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(),
    )
    engine = KnowledgePolicyEngine(runtime)
    state = build_knowledge_runtime_state(runtime, current(parent=True))
    stripped = KnowledgeRuntimeState(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
    )
    for supplied in [state, stripped]:
        for target in [
            "composition.symmetry_mode",
            "metal.components.shank.coating.material",
            "decorative_elements.ornament.motif",
        ]:
            with pytest.raises(ValueError, match="canonical v2"):
                engine.evaluate(supplied, proposal(target, "changed"))


@pytest.mark.parametrize("value", [{}, {"symmetry_mode": None}, {"not_a_field": "x"}, "invalid"])
def test_partial_or_malformed_aggregate_is_not_a_patch(engine, value):
    with pytest.raises(ValueError, match="invalid or incomplete"):
        evaluate(engine, revision_v1_1(), proposal("composition", value))


def test_none_unknown_not_applicable_and_keep(engine):
    data = current().model_dump(mode="json")
    data["design"]["composition"]["value"]["rhythm"] = {
        "availability": "unknown",
        "origin": "unknown",
    }
    data["design"]["construction"]["clasp"] = dict(
        availability="not_applicable",
        reason="Synthetic ring has no clasp",
        source=SOURCE.model_dump(mode="json"),
        locked=True,
    )
    revision = DesignRevisionV1_1.model_validate(data)
    state = build_knowledge_runtime_state(engine.runtime, revision)
    assert state.get("composition.rhythm").semantic_state == RuntimeSemanticState.MISSING
    assert state.get("metal.finish").semantic_state == RuntimeSemanticState.MISSING
    assert state.get("construction.clasp").semantic_state == RuntimeSemanticState.NOT_APPLICABLE
    assert evaluate(engine, revision, proposal("construction.clasp", "hook")).reason == "locked"
    assert (
        evaluate(
            engine,
            revision,
            proposal("composition.rhythm", "regular", preservation=PreservationIntent.KEEP),
        ).outcome
        == "KEPT"
    )


@pytest.mark.parametrize("metadata", ["source", "uncertainty", "origin"])
def test_full_derived_locked_metadata_is_preserved(engine, metadata):
    data = current().model_dump(mode="json")
    data["design"]["composition"]["value"]["symmetry_mode"] = dict(
        availability="value",
        origin="derived",
        value="asymmetrical",
        sources=[
            dict(
                kind="knowledge",
                record_id="synthetic",
                version="1.0.0",
                recorded_at=NOW.isoformat(),
            )
        ],
        uncertainty="Synthetic evidence only",
        confirmed=True,
        locked=True,
    )
    revision = DesignRevisionV1_1.model_validate(data)
    value = deepcopy(data["design"]["composition"]["value"])
    if metadata == "source":
        value["symmetry_mode"]["sources"][0]["record_id"] = "different"
    elif metadata == "uncertainty":
        value["symmetry_mode"]["uncertainty"] = "Changed uncertainty"
    else:
        value["symmetry_mode"] = explicit("asymmetrical", True)
    assert evaluate(engine, revision, proposal("composition", value)).reason == "locked"


def test_determinism_and_inputs_unchanged(engine):
    revision = current(parent=True)
    state = build_knowledge_runtime_state(engine.runtime, revision)
    before = revision.model_dump_json(), state.model_dump_json()
    change = proposal("composition.symmetry_mode", "radial")
    assert CANONICAL_POLICY_EVALUATION_VERSION == "2.0.0"
    assert evaluate(engine, revision, change, effective_state=state) == evaluate(
        engine, revision, change, effective_state=state
    )
    assert before == (revision.model_dump_json(), state.model_dump_json())


def test_explicit_empty_replacement_without_protected_children(engine):
    data = revision_v1_1().model_dump(mode="json")
    data["design"]["metal"]["components"] = explicit(
        [{"component_id": "shank", "material": explicit("gold")}]
    )
    revision = DesignRevisionV1_1.model_validate(data)
    assert evaluate(engine, revision, proposal("metal.components", [])).outcome == "APPLIED"


def test_duplicate_stable_ids_fail_enclosing_schema_validation(engine):
    revision = current("component")
    value = revision.design.model_dump(mode="json")["metal"]["components"]["value"]
    with pytest.raises(ValueError, match="invalid or incomplete"):
        evaluate(engine, revision, proposal("metal.components", value + deepcopy(value)))


def test_v1_leaf_and_stable_side_group_behavior(engine):
    path = (
        Path(__file__).resolve().parents[3] / "specs/jewelry-design-schema/fixtures/valid/ring.json"
    )
    revision = DesignRevision.model_validate_json(path.read_text())
    state = build_knowledge_runtime_state(engine.runtime, revision)
    assert state.existing_group_ids == ("accents",)
    assert evaluate(engine, revision, proposal("metal.color", "yellow")).reason == "locked"
    assert (
        evaluate(
            engine,
            revision,
            proposal("side_stones.missing.quantity", {"value": 2, "scope": "per_item"}),
        ).outcome
        == "BLOCKED"
    )


def test_foreign_knowledge_source_is_not_masked_by_canonical_lock(engine):
    with pytest.raises(ValueError, match="does not belong"):
        evaluate(
            engine,
            current(parent=True),
            proposal(
                "composition.symmetry_mode",
                "radial",
                semantic_state=RuntimeSemanticState.RECOMMENDED,
                provenance=RuntimeProvenance.KNOWLEDGE_INFERRED,
                source_id="foreign-evidence",
            ),
        )


def test_assumed_locked_rationale_is_protected(engine):
    data = current().model_dump(mode="json")
    data["design"]["composition"]["value"]["symmetry_mode"] = dict(
        availability="value",
        origin="assumed",
        value="asymmetrical",
        source=dict(kind="rule", rule_id="synthetic", version="1.0.0", recorded_at=NOW.isoformat()),
        rationale="Synthetic rationale",
        confirmed=True,
        locked=True,
    )
    revision = DesignRevisionV1_1.model_validate(data)
    value = revision.design.composition.value.model_dump(mode="json")
    value["symmetry_mode"]["rationale"] = "Changed rationale"
    assert evaluate(engine, revision, proposal("composition", value)).reason == "locked"


def test_canonical_v1_keeps_flat_leaf_contract_including_untyped_proposal_values():
    path = (
        Path(__file__).resolve().parents[3] / "specs/jewelry-design-schema/fixtures/valid/ring.json"
    )
    revision = DesignRevision.model_validate_json(path.read_text())
    runtime = CompiledKnowledgeLibrary(
        package_id="test.legacy",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(),
    )
    engine = KnowledgePolicyEngine(runtime)
    state = build_knowledge_runtime_state(runtime, revision)
    change = proposal("metal.finish", None)
    assert engine.evaluate(state, change) == evaluate(engine, revision, change)


@pytest.mark.parametrize("kind", ["component", "decorative"])
@pytest.mark.parametrize("iterator_kind", ["generator", "list_iterator", "legacy_sequence"])
def test_r1_one_shot_replacement_is_rejected_without_consumption(engine, kind, iterator_kind):
    """R1-001/002/005/006: never check a generator then return its exhausted value."""
    revision = current(kind)
    target, full = aggregate(revision.design.model_dump(mode="json"), kind)
    complete = full["value"]
    one_shot = (item for item in complete) if iterator_kind == "generator" else iter(complete)
    if iterator_kind == "legacy_sequence":

        class OneShotSequence:
            def __init__(self):
                self.items = iter(complete)

            def __getitem__(self, index):
                try:
                    return next(self.items)
                except StopIteration:
                    raise IndexError from None

        one_shot = OneShotSequence()
    change = proposal(target, one_shot)
    for _ in range(2):
        with pytest.raises(ValueError, match="repeatable replacement snapshot"):
            evaluate(engine, revision, change)
    assert list(one_shot) == complete


@pytest.mark.parametrize("container", ["dict", "tuple", "model"])
def test_r1_nested_iterator_is_rejected_before_validation(engine, container):
    """R1-003/006: preflight must inspect nested State/provenance containers."""
    from jewelai_domain.models_v1_1 import MetalComponentV1_1

    revision = current("component")
    full = revision.design.model_dump(mode="json")["metal"]["components"]["value"]
    sources = [
        dict(kind="knowledge", record_id="synthetic", version="1.0.0", recorded_at=NOW.isoformat())
    ]
    one_shot = (item for item in sources)
    full[0]["material"] = dict(
        availability="value",
        origin="derived",
        value="platinum",
        sources=one_shot,
        uncertainty="Synthetic evidence only",
        confirmed=True,
        locked=True,
    )
    value = full
    if container == "tuple":
        value = tuple(full)
    elif container == "model":
        # Deliberately bypass construction validation: canonical evaluation must
        # still reject unsafe content before Pydantic can consume it.
        value = (MetalComponentV1_1.model_construct(**full[0]),)
    change = proposal("metal.components", value)
    for _ in range(2):
        with pytest.raises(ValueError, match="repeatable replacement snapshot"):
            evaluate(engine, revision, change)
    assert list(one_shot) == sources


@pytest.mark.parametrize("kind", ["component", "decorative"])
@pytest.mark.parametrize("form", ["list", "tuple", "typed"])
@pytest.mark.parametrize("locked", [True, False], ids=["preserve-locked", "unlocked-positive"])
def test_r1_validated_snapshot_is_the_serialized_returned_value(engine, kind, form, locked):
    """R1-004..007/009: coercion, serialization, revision parity and immutability."""
    revision_data = current(kind).model_dump(mode="json")
    target, wrapper = aggregate(revision_data["design"], kind)
    child = "material" if kind == "component" else "motif"
    wrapper["value"][0][child]["locked"] = locked
    wrapper["value"][0][child]["confirmed"] = locked
    revision = DesignRevisionV1_1.model_validate(revision_data)
    before_revision = revision.model_dump_json()
    full = deepcopy(wrapper["value"])
    # Existing datetime parsing accepts equivalent UTC representations. The
    # checked serialization must be returned, not the raw input spelling.
    full[0][child]["source"]["recorded_at"] = NOW.isoformat()
    full[0]["finish" if kind == "component" else "location"] = explicit("synthetic")
    if not locked:
        full[0][child]["value"] = "changed"
    design_data = revision.design.model_dump(mode="json")
    _, expected_wrapper = aggregate(design_data, kind)
    expected_wrapper["value"] = deepcopy(full)
    checked_design = DesignV1_1.model_validate(design_data)
    _, checked_wrapper = aggregate(checked_design.model_dump(mode="json"), kind)
    expected = checked_wrapper["value"]
    value = full if form == "list" else tuple(full)
    if form == "typed":
        value = (
            checked_design.metal.components.value
            if kind == "component"
            else checked_design.decorative_elements.value
        )
    change = proposal(target, value)
    before_input = change.model_dump_json()
    first = evaluate(engine, revision, change)
    second = evaluate(engine, revision, change)
    assert first.outcome == second.outcome == "APPLIED"
    serialized = json.loads(first.model_dump_json())
    assert serialized["result"]["value"] == serialized["proposed"]["value"] == expected
    assert first.model_dump_json() == second.model_dump_json()
    assert change.model_dump_json() == before_input
    assert revision.model_dump_json() == before_revision
    # Check the actual serialized APPLIED value through the authoritative edit,
    # not merely an independently constructed value that passed the guard.
    expected_wrapper["value"] = serialized["result"]["value"]
    updated = revise_design(revision, DesignV1_1.model_validate(design_data), **edit_args(revision))
    _, updated_wrapper = aggregate(updated.design.model_dump(mode="json"), kind)
    assert updated_wrapper["value"] == expected
    # A supported mutable input cannot remain aliased into the returned result.
    if form != "typed":
        full[0][child]["value"] = "caller-change-after-evaluation"
        assert json.loads(first.model_dump_json()) == serialized


@pytest.mark.parametrize("kind", ["component", "decorative"])
def test_r1_serialized_blocked_replacement_retains_locked_descendants(engine, kind):
    """R1-009: removal rejected by revisions cannot return applicable policy output."""
    revision = current(kind)
    data = revision.design.model_dump(mode="json")
    target, wrapper = aggregate(data, kind)
    original = deepcopy(wrapper["value"])
    wrapper["value"] = []
    result = evaluate(engine, revision, proposal(target, []))
    assert (result.outcome, result.reason) == ("BLOCKED", "locked")
    assert json.loads(result.model_dump_json())["result"]["value"] == original
    with pytest.raises(RevisionConflict, match="Locked field"):
        revise_design(revision, DesignV1_1.model_validate(data), **edit_args(revision))
