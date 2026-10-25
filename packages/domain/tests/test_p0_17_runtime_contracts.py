import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from jewelai_domain.knowledge_library import CompiledKnowledgeLibrary
from jewelai_domain.knowledge_policy import build_knowledge_runtime_state
from jewelai_domain.knowledge_targets_v1_1 import (
    PRODUCT_STATE_TARGET_FAMILIES_V1_1,
    is_allowed_product_state_target_v1_1,
    target_family_from_concrete,
)
from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import (
    DesignRevisionV1_1,
    upgrade_design_revision_v1_to_v1_1,
)
from jewelai_domain.reference_bindings import FeatureBinding, ReferenceBinding
from jewelai_domain.schema_v1_1 import json_schema_v1_1
from jewelai_domain.visualization_verification import (
    VerificationCheck,
    VerificationSubject,
    VisualizationVerificationResult,
)

ROOT = Path(__file__).resolve().parents[3]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"
REFERENCE_SCHEMA = ROOT / "specs" / "reference-bindings" / "schema-v1.0.0.json"
VERIFICATION_SCHEMA = (
    ROOT / "specs" / "visualization-verification" / "schema-v1.0.0.json"
)


def runtime():
    return CompiledKnowledgeLibrary(
        package_id="jewelai.test.p0_17",
        artifact_version="1.0.0",
        sources=(),
        claims=(),
        domain_knowledge=(),
        language_mappings=(),
        policies=(),
    )


def test_v1_upgrade_is_additive_and_preserves_existing_design_values():
    v1 = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    upgraded = upgrade_design_revision_v1_to_v1_1(v1)

    assert upgraded.schema_version == "1.1.0"
    assert upgraded.design_id == v1.design_id
    assert upgraded.revision_id == v1.revision_id
    assert upgraded.revision == v1.revision
    assert upgraded.design.metal.material == v1.design.metal.material
    assert upgraded.design.center_stone.shape == v1.design.center_stone.shape
    assert upgraded.design.side_stones[0].group_id == v1.design.side_stones[0].group_id
    assert upgraded.design.center_stone.variety_or_type is None
    assert upgraded.design.halo.enabled is None
    assert upgraded.design.composition is None


def test_v1_1_json_schema_validates_upgraded_revision():
    v1 = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    upgraded = upgrade_design_revision_v1_to_v1_1(v1)
    schema = json_schema_v1_1()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    assert not list(validator.iter_errors(upgraded.model_dump(mode="json")))


def test_v1_1_target_grammar_contains_all_frozen_product_state_families():
    assert len(PRODUCT_STATE_TARGET_FAMILIES_V1_1) == 148
    assert is_allowed_product_state_target_v1_1("center_stone.variety_or_type")
    assert is_allowed_product_state_target_v1_1("composition.symmetry_mode")
    assert (
        target_family_from_concrete("side_stones.accents.stones.shape")
        == "side_stones.{group_id}.stones.shape"
    )
    assert (
        target_family_from_concrete("metal.components.shank.material")
        == "metal.components[].material"
    )
    assert (
        target_family_from_concrete("decorative_elements.floral.motif")
        == "decorative_elements[].motif"
    )
    assert not is_allowed_product_state_target_v1_1("references.feature_bindings")
    assert not is_allowed_product_state_target_v1_1("verification.geometry_plausibility")
    assert not is_allowed_product_state_target_v1_1("presentation.camera_view")


def test_knowledge_projection_accepts_v1_1_without_changing_v1_runtime_identity():
    v1 = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    upgraded = upgrade_design_revision_v1_to_v1_1(v1)
    compiled = runtime()

    projected = build_knowledge_runtime_state(compiled, upgraded)

    assert projected.package_id == compiled.package_id
    assert projected.runtime_sha256 == compiled.sha256
    assert projected.get("center_stone.variety_or_type").semantic_state == "MISSING"
    assert projected.get("halo.enabled").semantic_state == "MISSING"
    assert projected.get("composition").semantic_state == "MISSING"


def test_reference_binding_runtime_matches_frozen_json_schema():
    binding = ReferenceBinding(
        binding_id="binding-1",
        asset_id="asset-1",
        reference_role="base_design",
        feature_bindings=(
            FeatureBinding(
                feature_path="center_stone.shape",
                relation="KEEP",
                provenance="user_text",
            ),
        ),
    )
    schema = json.loads(REFERENCE_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        binding.model_dump(mode="json", exclude_none=True)
    )

    with pytest.raises(ValidationError, match="feature bindings must be unique"):
        ReferenceBinding(
            binding_id="binding-duplicate",
            asset_id="asset-1",
            reference_role="base_design",
            feature_bindings=(
                binding.feature_bindings[0],
                binding.feature_bindings[0],
            ),
        )


def test_visualization_verification_runtime_matches_frozen_json_schema():
    result = VisualizationVerificationResult(
        verification_id="verification-1",
        subject=VerificationSubject(generation_run_id="run-1"),
        overall_status="UNVERIFIABLE",
        action="ASK",
        checks=(
            VerificationCheck(
                check_id="check-1",
                dimension="observability_confidence",
                status="UNVERIFIABLE",
            ),
        ),
    )
    schema = json.loads(VERIFICATION_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))

    with pytest.raises(ValidationError, match="verification check IDs must be unique"):
        VisualizationVerificationResult(
            verification_id="verification-duplicate",
            subject=VerificationSubject(generation_run_id="run-1"),
            overall_status="FAIL",
            action="RETRY",
            checks=(result.checks[0], result.checks[0]),
        )


def test_v1_1_revision_rejects_duplicate_new_component_ids():
    v1 = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    payload = upgrade_design_revision_v1_to_v1_1(v1).model_dump(mode="json")
    source = payload["event"]["source"]
    payload["design"]["decorative_elements"] = {
        "availability": "value",
        "origin": "explicit",
        "source": source,
        "value": [
            {"element_id": "motif", "motif": None},
            {"element_id": "motif", "motif": None},
        ],
        "confirmed": False,
        "locked": False,
    }

    with pytest.raises(ValidationError, match="decorative element IDs must be unique"):
        DesignRevisionV1_1.model_validate(payload)
