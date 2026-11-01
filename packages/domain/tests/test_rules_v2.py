"""The Rules2 material conflict is contextual, never universal metal requiredness."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_rules import satisfied_revision

from jewelai_domain import (
    load_domain_dictionary,
    load_question_catalog,
    load_role_profiles,
    load_rules,
)
from jewelai_domain.clarification_state import (
    CauseDefinition,
    EvidenceScope,
    evidence_bytes,
    evidence_hash,
)
from jewelai_domain.models import DesignRevision
from jewelai_domain.questions import SchemaTarget
from jewelai_domain.rules import RulesBundle
from jewelai_domain.rules_v2 import RuleContextV2, RulesBundleV2

ROOT = Path(__file__).resolve().parents[3]


def registry():
    roles = load_role_profiles(ROOT / "data/roles/v1.0.0.json")
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    questions = load_question_catalog(
        ROOT / "data/questions/v2.0.0.json", roles=roles, dictionary=dictionary
    )
    return load_rules(
        ROOT / "data/rules/v2.0.0.json",
        roles=roles,
        dictionary=dictionary,
        questions=questions,
    )


def material_context(revision):
    scope = EvidenceScope(organization_id=uuid4(), session_id=uuid4(), design_id=revision.design_id)
    pins = dict(
        design_schema_version=revision.schema_version,
        role_artifact_version="1.0.0",
        dictionary_artifact_version="1.0.0",
        question_schema_version="2.0.0",
        question_artifact_version="2.0.0",
        rules_schema_version="2.0.0",
        rules_artifact_version="2.0.0",
        prompt_template_artifact_version="1.0.0",
        dictionary_sha256="a" * 64,
        question_sha256="b" * 64,
        rules_sha256="c" * 64,
    )
    target = dict(
        concrete_target="metal.material", owner_kind="product_body", owner_id=None, group_id=None
    )
    rule = dict(
        artifact_version="2.0.0",
        artifact_sha256="c" * 64,
        rule_id="ask_unresolved_product_body_material",
        rule_version="1.0.0",
    )
    definition = dict(
        schema_version="1.0.0",
        scope=scope.model_dump(mode="json"),
        target=target,
        kind="material_alternative",
        origin_cycle_id=str(uuid4()),
        origin_revision_id=str(revision.revision_id),
        origin_plan_id=str(uuid4()),
        source_candidate_refs=[],
        source_conflict_id="conflict_" + "a" * 64,
        rule_ref=rule,
        release_pin=dict(
            package_id="test",
            artifact_version="1.0.0",
            runtime_sha256="a" * 64,
            validation_report_sha256="b" * 64,
        ),
        artifact_pins=pins,
        resolution_predicate=dict(
            kind="material_choice",
            target="metal.material",
            offered_values=["gold", "platinum"],
            conflict_id="conflict_" + "a" * 64,
        ),
    )
    definition["cause_id"] = (
        "cause_"
        + hashlib.sha256(b"jewelai.f04.cause/1.0.0\0" + evidence_bytes(definition)).hexdigest()
    )
    definition["content_hash"] = evidence_hash(definition)
    validated = CauseDefinition.model_validate(definition)
    core = dict(
        schema_version="1.0.0",
        scope=scope.model_dump(mode="json"),
        current_revision_id=str(revision.revision_id),
        revision_sha256=evidence_hash(revision),
        profile="jewelai.prompt-enrichment.f04/2.0.0",
        cause_states=[
            dict(
                cause_id=validated.cause_id,
                status="OPEN",
                criticality="BLOCKING",
                offer_state="AVAILABLE",
                last_answer_ref=None,
                resolution_ref=None,
                superseded_by_cause_id=None,
                rule_ref=rule,
                availability_target_ref=target,
            )
        ],
    )
    core["content_hash"] = evidence_hash(core)
    return RuleContextV2(frontier_core=core, cause_definitions=(validated,))


def test_f04_material_rule_is_contextual_and_legacy_gaps_are_unchanged():
    rules = registry()
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    revision = satisfied_revision(revision)
    data = revision.model_dump(mode="json")
    data["design"]["metal"]["material"] = None
    revision = DesignRevision.model_validate(data)
    before = revision.model_dump_json()
    assert rules.required_targets == tuple(SchemaTarget)
    assert rules.evaluate(revision, "retail_client").decision == "ready"
    decision = rules.evaluate(
        revision,
        "retail_client",
        unresolved_context=material_context(revision),
    )
    assert decision.question_id == "METAL_MATERIAL"
    assert (decision.priority, decision.tie_order) == (950, 15)
    assert decision.concrete_target == "metal.material"
    assert revision.model_dump_json() == before


def test_f04_rule_artifact_and_schema_are_exact():
    payload = json.loads((ROOT / "data/rules/v2.0.0.json").read_text())
    old = json.loads((ROOT / "data/rules/v1.0.0.json").read_text())
    assert payload["rules"][:-1] == old["rules"]
    assert payload["required_targets"] == old["required_targets"]
    RulesBundleV2.model_validate(payload)
    with pytest.raises(ValidationError):
        RulesBundle.model_validate(payload)
    assert (
        json.loads((ROOT / "specs/rules/v2.0.0/schema.json").read_text())
        == RulesBundleV2.model_json_schema()
    )


@pytest.mark.parametrize(
    "field,value", (("priority", 999), ("tie_order", 16), ("target", "metal.color"))
)
def test_f04_rule_cannot_silently_expand_approved_policy(field, value):
    payload = json.loads((ROOT / "data/rules/v2.0.0.json").read_text())
    payload["rules"][-1][field] = value
    with pytest.raises(ValidationError):
        RulesBundleV2.model_validate(payload)
