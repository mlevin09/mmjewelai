import inspect
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_domain import (
    Design,
    DesignRevision,
    RevisionConflict,
    RoleId,
    UnknownRoleError,
    UnsupportedLocaleError,
    confirm_field,
    load_role_profiles,
    lock_field,
    revise_design,
)
from jewelai_domain.models import MessageSource
from jewelai_domain.roles import RoleProfileBundle
from jewelai_domain.roles_schema import role_profiles_json_schema

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "roles" / "v1.0.0.json"
SCHEMA = ROOT / "specs" / "roles" / "schema.json"
DESIGN_FIXTURE = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
NOW = datetime(2026, 9, 23, tzinfo=UTC)
SOURCE = MessageSource(message_id="role-invariant-test", recorded_at=NOW)


@pytest.fixture
def catalog_data():
    return json.loads(CATALOG.read_text())


@pytest.fixture
def registry():
    return load_role_profiles(CATALOG)


def test_committed_role_schema_matches_generator_and_validates_catalog(catalog_data):
    generated = role_profiles_json_schema()
    assert json.loads(SCHEMA.read_text()) == generated
    Draft202012Validator.check_schema(generated)
    Draft202012Validator(generated).validate(catalog_data)


def test_loads_all_six_canonical_roles_in_stable_order(registry):
    assert tuple(registry) == tuple(RoleId)
    assert [role.value for role in registry] == [
        "retail_client",
        "sales_manager",
        "buyer",
        "marketing",
        "jewelry_designer",
        "industrial_designer",
    ]
    assert registry.artifact_version == "1.0.0"


def test_lookup_is_deterministic_and_versions_are_pinned(registry):
    first = registry.get_profile("buyer")
    second = load_role_profiles(CATALOG).get_profile(RoleId.BUYER)
    assert first == second
    assert first.artifact_version == "1.0.0"
    assert first.schema_version == "1.0.0"
    assert first.design_schema_version == "1.0.0"


@pytest.mark.parametrize("role_id", RoleId)
def test_every_role_uses_shared_domain_contract_without_authority(registry, role_id):
    profile = registry.get_profile(role_id)
    assert profile.design_schema_version == "1.0.0"
    assert profile.authorization_effect == "none"
    assert profile.question_policy.selection == "deterministic_rules"
    assert profile.default_policy.mode == "no_unapproved_defaults"
    assert profile.question_policy.budget == "product_review_required"


def test_retail_and_industrial_policies_are_distinct(registry):
    retail = registry.get_profile(RoleId.RETAIL_CLIENT)
    industrial = registry.get_profile(RoleId.INDUSTRIAL_DESIGNER)
    assert (retail.vocabulary.value, retail.detail_level.value) == ("plain", "essential")
    assert (industrial.vocabulary.value, industrial.detail_level.value) == (
        "technical_engineering",
        "engineering",
    )
    assert industrial.derivation_policy.mode.value == "request_exact_when_required"


@pytest.mark.parametrize(
    ("requested", "resolved"),
    [("en", "en"), ("EN-us", "en"), ("ru_RU", "ru")],
)
def test_locale_resolution_is_explicit_and_deterministic(registry, requested, resolved):
    assert registry.resolve_locale("retail_client", requested) == resolved


def test_unsupported_locale_is_rejected(registry):
    with pytest.raises(UnsupportedLocaleError, match="Unsupported locale"):
        registry.resolve_locale("retail_client", "fr-CA")


@pytest.mark.parametrize("role_id", ["administrator", "Retail_Client", "industrial-designer"])
def test_unknown_or_noncanonical_lookup_is_rejected(registry, role_id):
    with pytest.raises(UnknownRoleError, match="Unknown canonical role"):
        registry.get_profile(role_id)


def test_duplicate_roles_are_rejected(catalog_data):
    catalog_data["profiles"][-1] = deepcopy(catalog_data["profiles"][0])
    with pytest.raises(ValidationError, match="unique"):
        RoleProfileBundle.model_validate(catalog_data)


def test_unknown_catalog_role_is_rejected(catalog_data):
    catalog_data["profiles"][0]["role_id"] = "administrator"
    with pytest.raises(ValidationError):
        RoleProfileBundle.model_validate(catalog_data)


def test_invalid_policy_value_is_rejected(catalog_data):
    catalog_data["profiles"][0]["question_policy"]["budget"] = "unlimited"
    with pytest.raises(ValidationError):
        RoleProfileBundle.model_validate(catalog_data)


def test_invalid_policy_combination_is_rejected_by_python_and_schema(catalog_data):
    catalog_data["profiles"][0]["detail_level"] = "engineering"
    with pytest.raises(ValidationError, match="Policy combination"):
        RoleProfileBundle.model_validate(catalog_data)
    assert list(Draft202012Validator(role_profiles_json_schema()).iter_errors(catalog_data))


def test_role_cannot_define_authorization_privileges(catalog_data):
    catalog_data["profiles"][0]["permissions"] = ["edit_locked_fields"]
    with pytest.raises(ValidationError, match="Extra inputs"):
        RoleProfileBundle.model_validate(catalog_data)


def transition_args(revision):
    return {
        "expected_revision_id": revision.revision_id,
        "source": SOURCE,
        "reason": "Role must not change domain transitions",
        "created_at": NOW,
    }


@pytest.mark.parametrize("role_id", RoleId)
def test_no_role_can_bypass_locked_constraints(registry, role_id):
    assert registry.get_profile(role_id).authorization_effect == "none"
    current = DesignRevision.model_validate_json(DESIGN_FIXTURE.read_text())
    data = current.design.model_dump(mode="json")
    data["metal"]["color"] = None
    with pytest.raises(RevisionConflict, match="Locked field"):
        revise_design(current, Design.model_validate(data), **transition_args(current))


@pytest.mark.parametrize("role_id", RoleId)
def test_no_role_can_bypass_revision_conflicts(registry, role_id):
    assert registry.get_profile(role_id).authorization_effect == "none"
    current = DesignRevision.model_validate_json(DESIGN_FIXTURE.read_text())
    options = transition_args(current)
    options["expected_revision_id"] = uuid4()
    with pytest.raises(RevisionConflict, match="Stale"):
        confirm_field(current, "center_stone.shape", **options)


@pytest.mark.parametrize("role_id", RoleId)
def test_no_role_can_bypass_confirmation_semantics(registry, role_id):
    assert registry.get_profile(role_id).authorization_effect == "none"
    current = DesignRevision.model_validate_json(DESIGN_FIXTURE.read_text())
    data = current.design.model_dump(mode="json")
    data["center_stone"]["shape"] = {
        "origin": "explicit",
        "value": "pear",
        "source": SOURCE.model_dump(mode="json"),
    }
    edited = revise_design(current, Design.model_validate(data), **transition_args(current))
    with pytest.raises(RevisionConflict, match="confirmed"):
        lock_field(edited, "center_stone.shape", **transition_args(edited))


def test_role_api_has_no_domain_transition_or_authorization_parameters():
    for operation in (revise_design, confirm_field, lock_field):
        parameters = inspect.signature(operation).parameters
        assert "role" not in parameters
        assert "permissions" not in parameters
