"""Contract-candidate invariants: latest canonical state wins over all assumptions."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from jewelai_domain.models_v1_1 import validate_design_revision
from jewelai_domain.smart_defaults_candidate import (
    DefaultCandidate,
    DefaultPolicyRule,
    select_default_candidates,
)

FIXTURE = (
    Path(__file__).resolve().parents[3] / "specs/jewelry-design-schema/fixtures/valid/ring.json"
)


@pytest.fixture
def wire():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def rule(path, value, *, jewelry_type="ring", rule_id="ring_default"):
    return DefaultPolicyRule(
        target_path=path,
        when_jewelry_type=jewelry_type,
        proposed_value=value,
        rule_id=rule_id,
        rule_version="1.0.0",
        rationale="Illustrative test-only policy, not an authorized default.",
    )


def project(wire, *rules, blocked=frozenset()):
    return select_default_candidates(wire, tuple(rules), blocked_targets=frozenset(blocked))


def test_only_missing_or_unknown_state_leaves_are_proposed(wire):
    rules = (
        rule("metal.finish", "polished", rule_id="finish_rule"),
        rule("center_stone.shape", "round", rule_id="shape_rule"),
        rule(
            "center_stone.dimensions",
            {
                "length": {"value": 8.0, "unit": "mm"},
                "width": {"value": 6.0, "unit": "mm"},
                "depth": {"value": 4.0, "unit": "mm"},
            },
            rule_id="size_rule",
        ),
    )
    original = deepcopy(wire)
    result = project(wire, *rules)
    assert [item.target_path for item in result] == ["center_stone.dimensions", "metal.finish"]
    assert wire == original
    assert all(item.source_kind == "rule" for item in result)
    assert all(DefaultCandidate.model_validate(item.model_dump()) == item for item in result)


def test_keep_lock_or_pending_parent_precludes_assumption(wire):
    one = rule("metal.finish", "polished")
    assert not project(wire, one, blocked={"metal"})
    assert not project(wire, one, blocked={"metal.finish"})
    # Existing LOCK and explicit values are always retained.
    assert not project(wire, rule("metal.color", "yellow"))


def test_no_substitution_for_explicit_not_applicable(wire):
    wire["design"]["metal"]["finish"] = {
        "availability": "not_applicable",
        "origin": "explicit",
        "reason": "An intentionally unfinished piece",
        "source": wire["event"]["source"],
        "confirmed": True,
        "locked": False,
        "value": None,
    }
    assert not project(wire, rule("metal.finish", "polished"))


def test_recompute_against_new_revision_replaces_older_proposal_not_user(wire):
    proposal = project(wire, rule("metal.finish", "polished"))[0]
    revised = deepcopy(wire)
    revised["parent_revision_id"] = revised["revision_id"]
    revised["revision_id"] = "33333333-3333-4333-8333-333333333333"
    revised["revision"] = 2
    revised["event"]["action"] = "edit"
    revised["design"]["metal"]["finish"] = {
        "availability": "value",
        "value": "matte",
        "confirmed": False,
        "locked": False,
        "origin": "explicit",
        "source": revised["event"]["source"],
    }
    assert project(revised, rule("metal.finish", "polished")) == ()
    assert proposal.basis_revision_id == wire["revision_id"]
    assert proposal.basis_revision_id != revised["revision_id"]
    assert validate_design_revision(revised).design.metal.finish.value == "matte"


def test_deterministic_by_revision_and_policy_and_type_condition(wire):
    rules = (
        rule("metal.finish", "polished"),
        rule("center_stone.setting", "prongs", rule_id="setting_rule"),
    )
    first = project(wire, *rules)
    assert first == project(wire, *reversed(rules))
    assert len({x.candidate_hash for x in first}) == 2
    assert project(wire, rule("metal.finish", "polished", jewelry_type="earrings")) == ()


def test_unknown_paths_and_duplicate_rules_fail_closed(wire):
    with pytest.raises(ValueError, match="unsupported canonical target"):
        project(wire, rule("unknown.field", "anything"))
    with pytest.raises(ValueError, match="target must refer"):
        project(wire, rule("metal.material.value", "anything"))
    with pytest.raises(ValueError, match="duplicate default target"):
        project(wire, rule("metal.finish", "polished"), rule("metal.finish", "matte"))


def test_candidate_hash_or_source_tampering_is_rejected(wire):
    original = project(wire, rule("metal.finish", "polished"))[0]
    bad = original.model_dump(mode="json")
    bad["proposed_value"] = "matte"
    with pytest.raises(ValueError, match="hash mismatch"):
        DefaultCandidate.model_validate(bad)


def test_same_target_rules_are_scoped_by_type(wire):
    rules = (
        rule("metal.finish", "polished"),
        rule("metal.finish", "matte", jewelry_type="earrings"),
    )
    assert project(wire, *rules)[0].proposed_value == "polished"
    wire["design"]["jewelry_type"]["value"] = "earrings"
    assert project(wire, *rules)[0].proposed_value == "matte"


def test_invalid_leaf_under_confirmed_parent_is_still_rejected(wire):
    with pytest.raises(ValueError, match="target must refer"):
        project(wire, rule("metal.material.value", "gold"))


@pytest.mark.parametrize("suffix", ["value", "reason"])
def test_unknown_wrapper_internals_are_not_canonical_targets(wire, suffix):
    assert wire["design"]["center_stone"]["dimensions"]["availability"] == "unknown"
    with pytest.raises(ValueError, match="target must refer|unsupported canonical target"):
        project(wire, rule(f"center_stone.dimensions.{suffix}", "anything"))
