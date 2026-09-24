import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_domain import load_domain_dictionary, load_question_catalog, load_role_profiles
from jewelai_domain.models import DesignRevision
from jewelai_domain.rules import (
    AssumeDecision,
    AvailableKnowledgeFact,
    BlockDecision,
    DeriveDecision,
    GapState,
    ProposedDomainUpdate,
    RuleRegistry,
    RulesBundle,
    analyze_gaps,
    load_rules,
)
from jewelai_domain.rules_schema import rules_json_schema

ROOT = Path(__file__).resolve().parents[3]
RULES = ROOT / "data" / "rules" / "v1.0.0.json"
ROLES = ROOT / "data" / "roles" / "v1.0.0.json"
DICTIONARY = ROOT / "data" / "dictionary" / "v1.0.0.json"
QUESTIONS = ROOT / "data" / "questions" / "v1.0.0.json"
DESIGN = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"


@pytest.fixture
def rules_data():
    return json.loads(RULES.read_text())


@pytest.fixture
def roles():
    return load_role_profiles(ROLES)


@pytest.fixture
def dictionary():
    return load_domain_dictionary(DICTIONARY)


@pytest.fixture
def questions(roles, dictionary):
    return load_question_catalog(QUESTIONS, roles=roles, dictionary=dictionary)


@pytest.fixture
def engine(roles, dictionary, questions):
    return load_rules(RULES, roles=roles, dictionary=dictionary, questions=questions)


@pytest.fixture
def ring():
    return DesignRevision.model_validate_json(DESIGN.read_text())


def rule(data, rule_id):
    return next(item for item in data["rules"] if item["rule_id"] == rule_id)


def build_engine(data, roles, dictionary, questions):
    return RuleRegistry(
        RulesBundle.model_validate(data),
        roles=roles,
        dictionary=dictionary,
        questions=questions,
    )


def explicit(revision, value, *, confirmed=True, locked=False):
    return {
        "availability": "value",
        "origin": "explicit",
        "value": value,
        "source": revision.event.source.model_dump(mode="json"),
        "confirmed": confirmed,
        "locked": locked,
    }


def changed_revision(revision, target, value):
    data = revision.model_dump(mode="json")
    if target == "center_stone.shape":
        data["design"]["center_stone"]["shape"] = value
    elif target == "center_stone.dimensions":
        data["design"]["center_stone"]["dimensions"] = value
    elif target == "center_stone.setting":
        data["design"]["center_stone"]["setting"] = value
    elif target == "metal.color":
        data["design"]["metal"]["color"] = value
    else:
        raise AssertionError(target)
    return DesignRevision.model_validate(data)


def dimensions_value():
    return {
        "length": {"value": 9.1, "unit": "mm"},
        "width": {"value": 7.2, "unit": "mm"},
        "depth": {"value": 4.8, "unit": "mm"},
    }


def knowledge_fact(**overrides):
    data = {
        "target": "center_stone.dimensions",
        "value": dimensions_value(),
        "source": {
            "kind": "knowledge",
            "record_id": "synthetic-kb-record",
            "version": "1.0.0",
            "recorded_at": "2026-09-24T09:00:00Z",
        },
        "uncertainty": "Synthetic test estimate; exact measurement remains preferable.",
        "match": {
            "jewelry_type": "ring",
            "center_stone_material": "emerald",
            "center_stone_weight": {"value": 3.0, "unit": "ct"},
        },
    }
    for key, value in overrides.items():
        data[key] = value
    return AvailableKnowledgeFact.model_validate(data)


def satisfied_revision(revision):
    result = changed_revision(
        revision,
        "center_stone.dimensions",
        explicit(revision, dimensions_value()),
    )
    return changed_revision(
        result,
        "center_stone.setting",
        explicit(revision, "prong_setting"),
    )


def test_committed_schema_matches_generator_and_validates_artifact(rules_data):
    generated = rules_json_schema()
    schema_path = ROOT / "specs" / "rules" / "schema.json"
    assert json.loads(schema_path.read_text()) == generated
    Draft202012Validator.check_schema(generated)
    Draft202012Validator(generated).validate(rules_data)
    RulesBundle.model_validate(rules_data)


def test_valid_catalog_loads_with_stable_versions_and_seed_count(engine, rules_data):
    assert engine.artifact_version == "1.0.0"
    assert len(engine) == 9
    assert rules_data["schema_version"] == "1.0.0"
    assert rules_data["artifact_version"] == "1.0.0"
    assert all(item["rule_version"] == "1.0.0" for item in rules_data["rules"])


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "2.0.0"), ("artifact_version", "latest")],
)
def test_invalid_bundle_versions_are_rejected(rules_data, field, value):
    rules_data[field] = value
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)


def test_invalid_rule_version_and_provenance_are_rejected(rules_data):
    rules_data["rules"][0]["rule_version"] = "v1"
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)
    rules_data = json.loads(RULES.read_text())
    rules_data["rules"][0]["provenance"]["review_status"] = "approved_by_engine"
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)


def test_requiredness_scope_order_is_explicit_and_stable(rules_data):
    rules_data["required_targets"].reverse()
    with pytest.raises(ValidationError, match="documented stable order"):
        RulesBundle.model_validate(rules_data)


def test_duplicate_and_malformed_rule_ids_are_rejected(rules_data):
    rules_data["rules"][1]["rule_id"] = rules_data["rules"][0]["rule_id"]
    with pytest.raises(ValidationError, match="Rule IDs must be unique"):
        RulesBundle.model_validate(rules_data)

    rules_data = json.loads(RULES.read_text())
    rules_data["rules"][0]["rule_id"] = "INVALID-RULE"
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)


@pytest.mark.parametrize(
    ("field", "value"),
    [("conditions", [{"kind": "python_eval"}]), ("action", {"kind": "execute"})],
)
def test_unsupported_condition_and_action_vocabularies_are_rejected(rules_data, field, value):
    rule(rules_data, "ask_center_stone_shape")[field] = value
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)


def test_unknown_target_and_question_are_rejected(rules_data):
    item = rule(rules_data, "ask_center_stone_shape")
    item["target"] = "center_stone.nonexistent"
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)

    rules_data = json.loads(RULES.read_text())
    rule(rules_data, "ask_center_stone_shape")["action"]["question_id"] = "UNKNOWN_QUESTION"
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)


def test_wrong_target_question_pairing_is_rejected(rules_data, roles, dictionary, questions):
    rule(rules_data, "ask_center_stone_shape")["action"]["question_id"] = "METAL_COLOR"
    with pytest.raises(ValueError, match="wrong target/question pairing"):
        build_engine(rules_data, roles, dictionary, questions)


@pytest.mark.parametrize(
    ("value", "category", "message"),
    [
        ("missing_shape", "stone_shape", "Unknown dictionary ID"),
        ("white", "metal_color", "Wrong dictionary category"),
        ("white", "stone_shape", "wrong category"),
    ],
)
def test_dictionary_references_are_validated(
    rules_data, roles, dictionary, questions, value, category, message
):
    item = rule(rules_data, "ask_center_stone_shape")
    item["conditions"].append(
        {
            "kind": "field_equals",
            "target": "center_stone.shape",
            "value": value,
            "dictionary_category": category,
        }
    )
    with pytest.raises(ValueError, match=message):
        build_engine(rules_data, roles, dictionary, questions)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("role_artifact_version", "role artifact version"),
        ("dictionary_artifact_version", "dictionary artifact version"),
        ("question_artifact_version", "question artifact version"),
    ],
)
def test_pinned_artifact_version_mismatches_fail(
    rules_data, roles, dictionary, questions, field, message
):
    rules_data[field] = "1.0.1"
    with pytest.raises(ValueError, match=message):
        build_engine(rules_data, roles, dictionary, questions)


@pytest.mark.parametrize("priority", [-1, 10_001, True, "high"])
def test_invalid_priorities_are_rejected(rules_data, priority):
    rules_data["rules"][0]["priority"] = priority
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(rules_data)


def test_duplicate_tie_order_is_rejected(rules_data):
    rules_data["rules"][1]["tie_order"] = rules_data["rules"][0]["tie_order"]
    with pytest.raises(ValidationError, match="globally unique"):
        RulesBundle.model_validate(rules_data)


def test_unknown_and_cyclic_dependencies_fail_closed(rules_data):
    rules_data["rules"][0]["depends_on"] = ["missing_rule"]
    with pytest.raises(ValidationError, match="Unknown rule dependencies"):
        RulesBundle.model_validate(rules_data)

    rules_data = json.loads(RULES.read_text())
    rules_data["rules"][0]["depends_on"] = [rules_data["rules"][1]["rule_id"]]
    rules_data["rules"][1]["depends_on"] = [rules_data["rules"][0]["rule_id"]]
    with pytest.raises(ValidationError, match="contains a cycle"):
        RulesBundle.model_validate(rules_data)


def test_static_conflicting_rules_are_rejected(rules_data):
    duplicate = deepcopy(rule(rules_data, "ask_center_stone_shape"))
    duplicate["rule_id"] = "conflicting_shape_block"
    duplicate["tie_order"] = 95
    duplicate["action"] = {"kind": "block"}
    rules_data["rules"].append(duplicate)
    with pytest.raises(ValidationError, match="Static rule conflict"):
        RulesBundle.model_validate(rules_data)


def test_gap_analyzer_distinguishes_absent_unknown_satisfied_and_locked(ring, questions):
    data = ring.model_dump(mode="json")
    data["design"]["center_stone"]["shape"] = None
    data["design"]["center_stone"]["dimensions"] = {
        "availability": "unknown",
        "origin": "unknown",
        "requirement": "required",
        "value": None,
        "confirmed": False,
        "locked": False,
    }
    revision = DesignRevision.model_validate(data)
    gaps = {
        gap.target.value: gap
        for gap in analyze_gaps(revision, questions=questions)
        if gap.group_id is None
    }
    assert gaps["center_stone.shape"].state == GapState.ABSENT
    assert gaps["center_stone.dimensions"].state == GapState.UNKNOWN
    assert gaps["metal.color"].state == GapState.SATISFIED
    assert gaps["metal.color"].confirmed and gaps["metal.color"].locked


def test_side_stone_groups_bind_and_sort_by_stable_group_id(ring, questions, engine):
    data = satisfied_revision(ring).model_dump(mode="json")
    base_group = data["design"]["side_stones"][0]
    data["design"]["side_stones"] = [
        {**deepcopy(base_group), "group_id": "z_group", "quantity": None},
        {**deepcopy(base_group), "group_id": "a_group", "quantity": None},
    ]
    revision = DesignRevision.model_validate(data)
    side_gaps = [
        gap
        for gap in analyze_gaps(revision, questions=questions)
        if gap.target.value == "side_stones[*].quantity"
    ]
    assert [gap.group_id for gap in side_gaps] == ["a_group", "z_group"]
    decision = engine.evaluate(revision, "retail_client")
    assert decision.decision == "ask"
    assert decision.concrete_target == "side_stones.a_group.quantity"


def test_ring_emerald_three_carat_missing_shape_asks_without_inventing_dimensions(ring, engine):
    before = ring.model_dump_json()
    unknown = {
        "availability": "unknown",
        "origin": "unknown",
        "requirement": "required",
        "value": None,
        "confirmed": False,
        "locked": False,
    }
    revision = changed_revision(ring, "center_stone.shape", unknown)
    decision = engine.evaluate(revision, "retail_client")
    assert decision.decision == "ask"
    assert decision.question_id.value == "CENTER_STONE_SHAPE"
    assert decision.target.value == "center_stone.shape"
    assert decision.proposed_change is None
    assert revision.design.center_stone.dimensions.value is None
    assert ring.model_dump_json() == before
    selected = next(item for item in decision.trace if item.selected)
    assert selected.rule_id == "ask_center_stone_shape"


def test_retail_with_matching_sourced_fact_proposes_schema_valid_derived_state(ring, engine):
    fact = knowledge_fact()
    decision = engine.evaluate(ring, "retail_client", knowledge_facts=(fact,))
    assert isinstance(decision, DeriveDecision)
    assert decision.target.value == "center_stone.dimensions"
    state = decision.proposed_change.state
    assert state.origin == "derived"
    assert state.value == fact.value
    assert state.sources == (fact.source,)
    assert state.uncertainty == fact.uncertainty
    assert not state.confirmed and not state.locked
    derive_trace = next(item for item in decision.trace if item.selected)
    knowledge_trace = next(
        item
        for item in derive_trace.conditions
        if item.condition_kind == "compatible_knowledge_fact"
    )
    assert knowledge_trace.source_ids == ("synthetic-kb-record",)


def test_industrial_designer_asks_exact_dimensions_even_with_kb_fact(ring, engine):
    decision = engine.evaluate(ring, "industrial_designer", knowledge_facts=(knowledge_fact(),))
    assert decision.decision == "ask"
    assert decision.question_id.value == "CENTER_STONE_DIMENSIONS"
    assert decision.reason_code.value == "EXACT_MEASUREMENT_REQUIRED"
    assert decision.proposed_change is None


def test_locked_metal_conflict_blocks_without_overwrite(ring, engine):
    before = ring.model_dump_json()
    decision = engine.evaluate(
        ring,
        "retail_client",
        proposed_update=ProposedDomainUpdate(target="metal.color", value="yellow"),
    )
    assert isinstance(decision, BlockDecision)
    assert decision.reason_code.value == "LOCKED_FIELD_CONFLICT"
    assert decision.target.value == "metal.color"
    assert decision.proposed_change is None
    assert ring.design.metal.color.value == "white"
    assert ring.model_dump_json() == before


def test_no_fact_or_nonmatching_fact_never_derives(ring, engine):
    without = engine.evaluate(ring, "retail_client")
    assert without.decision == "ask"
    assert without.question_id.value == "CENTER_STONE_DIMENSIONS"
    assert without.reason_code.value == "NO_VALID_KB_MATCH"

    nonmatching = knowledge_fact(
        match={
            "jewelry_type": "ring",
            "center_stone_material": "diamond",
            "center_stone_weight": {"value": 3.0, "unit": "ct"},
        }
    )
    decision = engine.evaluate(ring, "retail_client", knowledge_facts=(nonmatching,))
    assert decision.decision == "ask"
    assert decision.proposed_change is None


def test_knowledge_fact_requires_source_uncertainty_and_valid_dictionary_context(ring, engine):
    data = knowledge_fact().model_dump(mode="json")
    del data["source"]
    with pytest.raises(ValidationError):
        AvailableKnowledgeFact.model_validate(data)
    data = knowledge_fact().model_dump(mode="json")
    del data["uncertainty"]
    with pytest.raises(ValidationError):
        AvailableKnowledgeFact.model_validate(data)
    invalid = knowledge_fact(
        match={
            "jewelry_type": "oval",
            "center_stone_material": "emerald",
            "center_stone_weight": {"value": 3.0, "unit": "ct"},
        }
    )
    with pytest.raises(ValueError, match="wrong category"):
        engine.evaluate(ring, "retail_client", knowledge_facts=(invalid,))


def test_fully_satisfied_required_scope_is_ready_and_byte_stable(ring, engine, questions):
    revision = satisfied_revision(ring)
    first = engine.evaluate(revision, "retail_client")
    second = engine.evaluate(revision, "retail_client")
    assert first.decision == "ready"
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert all(
        gap.state == GapState.SATISFIED for gap in analyze_gaps(revision, questions=questions)
    )


def test_catalog_order_does_not_change_decision_or_trace(
    rules_data, roles, dictionary, questions, ring, engine
):
    rules_data["rules"].reverse()
    reordered = build_engine(rules_data, roles, dictionary, questions)
    assert reordered.evaluate(ring, "retail_client") == engine.evaluate(ring, "retail_client")


def test_runtime_conflict_returns_explicit_bounded_block(
    rules_data, roles, dictionary, questions, ring
):
    exact = rule(rules_data, "ask_exact_center_stone_dimensions")
    exact["conditions"][1] = {"kind": "role_is", "role_id": "retail_client"}
    conflict_engine = build_engine(rules_data, roles, dictionary, questions)
    decision = conflict_engine.evaluate(ring, "retail_client", knowledge_facts=(knowledge_fact(),))
    assert isinstance(decision, BlockDecision)
    assert decision.reason_code.value == "RULE_CONFLICT"
    assert decision.conflict_rule_ids == (
        "ask_exact_center_stone_dimensions",
        "derive_center_stone_dimensions",
    )


def test_runtime_conflict_aggregates_three_rules_in_stable_sorted_order(
    rules_data, roles, dictionary, questions, ring
):
    exact = rule(rules_data, "ask_exact_center_stone_dimensions")
    exact["conditions"][1] = {"kind": "role_is", "role_id": "retail_client"}

    third = deepcopy(exact)
    third["rule_id"] = "block_conflicting_center_stone_dimensions"
    third["tie_order"] = 95
    third["conditions"].append(
        {
            "kind": "field_equals",
            "target": "center_stone.shape",
            "value": "oval",
            "dictionary_category": "stone_shape",
        }
    )
    third["action"] = {"kind": "block"}
    rules_data["rules"].append(third)

    conflict_engine = build_engine(rules_data, roles, dictionary, questions)
    decision = conflict_engine.evaluate(ring, "retail_client", knowledge_facts=(knowledge_fact(),))
    assert isinstance(decision, BlockDecision)
    assert decision.reason_code.value == "RULE_CONFLICT"
    assert decision.conflict_rule_ids == (
        "ask_exact_center_stone_dimensions",
        "block_conflicting_center_stone_dimensions",
        "derive_center_stone_dimensions",
    )


def assumption_rule(data):
    item = deepcopy(rule(data, "ask_metal_color"))
    item.update(
        {
            "rule_id": "approved_test_assumption",
            "priority": 1100,
            "tie_order": 95,
            "conditions": [{"kind": "role_is", "role_id": "retail_client"}],
            "action": {
                "kind": "assume",
                "value": "yellow",
                "dictionary_category": "metal_color",
                "rationale": "Synthetic approved-policy contract test.",
                "recorded_at": "2026-09-24T09:00:00Z",
            },
            "reason_code": "APPROVED_ASSUMPTION",
            "reason": "Synthetic assumption contract test.",
        }
    )
    data["rules"].append(item)


def test_assume_contract_uses_rule_source_and_rationale_but_seed_has_no_assumptions(
    rules_data, roles, dictionary, questions, ring
):
    assert all(item["action"]["kind"] != "assume" for item in rules_data["rules"])
    assumption_rule(rules_data)
    assumption_engine = build_engine(rules_data, roles, dictionary, questions)
    revision = changed_revision(ring, "metal.color", None)
    decision = assumption_engine.evaluate(revision, "retail_client")
    assert isinstance(decision, AssumeDecision)
    assert decision.proposed_change.state.origin == "assumed"
    assert decision.proposed_change.state.source.rule_id == "approved_test_assumption"
    assert decision.proposed_change.state.rationale
    assert not decision.proposed_change.state.confirmed
    assert not decision.proposed_change.state.locked


def test_derive_or_assume_can_never_overwrite_a_locked_target(
    rules_data, roles, dictionary, questions, ring
):
    assumption_rule(rules_data)
    assumption_engine = build_engine(rules_data, roles, dictionary, questions)
    decision = assumption_engine.evaluate(ring, "retail_client")
    assert isinstance(decision, BlockDecision)
    assert decision.reason_code.value == "LOCKED_FIELD_CONFLICT"
    assert decision.proposed_change is None


def test_rule_engine_has_no_dynamic_execution_network_provider_or_revision_creation():
    import jewelai_domain.rules as rules_module

    source = inspect.getsource(rules_module)
    assert "eval(" not in source
    assert "exec(" not in source
    assert "requests" not in source
    assert "httpx" not in source
    assert "openai" not in source.casefold()
    assert "gemini" not in source.casefold()
    assert "uuid4" not in source
    assert "DesignRevision(" not in source


def test_seed_contains_no_weight_to_dimensions_or_unapproved_defaults(rules_data):
    serialized = json.dumps(rules_data, ensure_ascii=False).casefold()
    assert "assume" not in {item["action"]["kind"] for item in rules_data["rules"]}
    assert "default" not in serialized
    assert "carat_to" not in serialized
    assert "weight_to" not in serialized
