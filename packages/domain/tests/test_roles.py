import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from tests.current_roles import current_roles

from jewelai_domain import (
    Design,
    DesignRevision,
    RevisionConflict,
    RoleId,
    UnknownRoleError,
    UnsupportedLocaleError,
    confirm_field,
    lock_field,
    revise_design,
)
from jewelai_domain.models import MessageSource
from jewelai_domain.roles_schema import role_profiles_json_schema

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data" / "roles" / "v1.0.0.json"
SCHEMA = ROOT / "specs" / "roles" / "schema.json"
DESIGN_FIXTURE = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
NOW = datetime(2026, 9, 23, tzinfo=UTC)
SOURCE = MessageSource(message_id="role-invariant-test", recorded_at=NOW)


@pytest.fixture
def registry():
    return current_roles()


def test_all_21_current_roles_and_context(registry):
    assert len(registry) == 21
    assert set(registry) == set(RoleId)
    private = registry.get_profile("RR-C25")
    professional = registry.get_profile("RR-C10")
    assert private.role_data["registry_entry"] != professional.role_data["registry_entry"]
    assert private.role_data["passport"]["maturity"] == "DRAFT_NOT_OWNER_APPROVED"
    assert professional.authorization_effect == "none"


@pytest.mark.parametrize(
    "role_id",
    [
        "retail_client",
        "sales_manager",
        "buyer",
        "marketing",
        "jewelry_designer",
        "industrial_designer",
        "RR-C01",
        "RR-C99",
    ],
)
def test_unknown_legacy_and_merged_ids_rejected(registry, role_id):
    with pytest.raises(UnknownRoleError):
        registry.get_profile(role_id)


def test_locale_resolution(registry):
    assert registry.resolve_locale("RR-C25", "ru_RU") == "ru"
    with pytest.raises(UnsupportedLocaleError):
        registry.resolve_locale("RR-C25", "fr")


def test_current_schema(registry):
    schema = role_profiles_json_schema()
    assert json.loads(SCHEMA.read_text()) == schema
    Draft202012Validator.check_schema(schema)
    for role_id in registry:
        Draft202012Validator(schema).validate(registry[role_id].model_dump(mode="json"))


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
