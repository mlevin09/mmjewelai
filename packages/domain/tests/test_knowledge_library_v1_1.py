import json
from pathlib import Path

import pytest

from jewelai_domain.knowledge_activation import ProductionValidationCheck
from jewelai_domain.knowledge_activation_v1_1 import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS_V1_1,
    ProductionValidationReportV1_1,
    promote_knowledge_runtime_v1_1,
)
from jewelai_domain.knowledge_library import compile_knowledge_library
from jewelai_domain.knowledge_library_v1_1 import (
    KnowledgeLibraryValidationErrorV1_1,
    compile_knowledge_library_v1_1,
    validate_knowledge_library_v1_1,
)
from jewelai_domain.knowledge_policy_v1_1 import (
    KnowledgePolicyEngineV1_1,
    build_knowledge_runtime_state_v1_1,
)
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from jewelai_domain.models import DesignRevision
from jewelai_domain.models_v1_1 import upgrade_design_revision_v1_to_v1_1

from test_knowledge_library import bundle as bundle_v1

ROOT = Path(__file__).resolve().parents[3]
RING = ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json"


def bundle_v1_1(*, target="composition.symmetry_mode", version="1.0.0"):
    return {
        "contract_version": "1.1.0",
        "package_id": "jewelai.test.v1_1",
        "artifact_version": version,
        "sources": [
            {
                "source_id": "DEC-V11",
                "title": "Reviewed internal v1.1 policy decision",
                "source_type": "INTERNAL_DECISION",
                "evidence_tier": "INTERNAL",
                "lifecycle_status": "REVIEWED",
                "language": "not_applicable",
            }
        ],
        "claims": [],
        "domain_knowledge": [],
        "language_mappings": [],
        "policies": [
            {
                "policy_id": "POL-V11",
                "target": target,
                "effect": "Use this reviewed policy only through deterministic runtime semantics.",
                "source_kind": "INTERNAL_PRODUCT_DECISION",
                "source_refs": ["DEC-V11"],
                "lifecycle_status": "REVIEWED",
            }
        ],
    }


def report(runtime, *, outcome="PASS"):
    return ProductionValidationReportV1_1(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome=outcome,
                evidence_ref=f"ci://v1.1/{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS_V1_1
        ),
    )


def test_v1_1_compiler_accepts_frozen_schema_v1_1_target():
    runtime, manifest = compile_knowledge_library_v1_1(bundle_v1_1())

    assert runtime.contract_version == "1.1.0"
    assert runtime.schema_version == "1.1.0"
    assert runtime.active_for_production is False
    assert runtime.policies[0].target == "composition.symmetry_mode"
    assert manifest.runtime_sha256 == runtime.sha256


@pytest.mark.parametrize(
    "target",
    [
        "references.feature_bindings",
        "verification.geometry_plausibility",
        "presentation.camera_view",
    ],
)
def test_v1_1_rejects_non_product_state_targets(target):
    with pytest.raises(KnowledgeLibraryValidationErrorV1_1, match="unavailable"):
        validate_knowledge_library_v1_1(bundle_v1_1(target=target))


@pytest.mark.parametrize(
    "target",
    [
        "side_stones.{group_id}.stones.treatment_status",
        "metal.components.{component_id}.material",
        "decorative_elements.{element_id}.motif",
    ],
)
def test_v1_1_accepts_stable_collection_templates(target):
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1(target=target))
    assert runtime.policies[0].target == target


def test_v1_1_runtime_policy_projects_schema_v1_1_state():
    v1 = DesignRevision.model_validate_json(RING.read_text(encoding="utf-8"))
    revision = upgrade_design_revision_v1_to_v1_1(v1)
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1())

    state = build_knowledge_runtime_state_v1_1(runtime, revision)
    engine = KnowledgePolicyEngineV1_1(runtime)

    assert state.runtime_sha256 == runtime.sha256
    assert state.get("composition.symmetry_mode").semantic_state == "MISSING"
    assert [item.policy_id for item in engine.policies_for("composition.symmetry_mode")] == [
        "POL-V11"
    ]


def test_v1_1_durable_publish_load_and_activation_are_exact(tmp_path):
    store = KnowledgeArtifactStoreV1_1(tmp_path)
    stored = store.publish(bundle_v1_1())
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1())
    validation = report(runtime)
    active = promote_knowledge_runtime_v1_1(runtime, validation)

    loaded = store.load_active_runtime(
        stored.package_id,
        stored.artifact_version,
        active_release=active,
        validation_report=validation,
    )

    assert loaded == active
    assert loaded.runtime_sha256 == stored.runtime_sha256
    assert loaded.validation_report_sha256 == validation.sha256


def test_v1_1_activation_remains_fail_closed():
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1())
    blocked = report(runtime, outcome="EXPECTED_GAP")

    with pytest.raises(ValueError, match="not eligible"):
        promote_knowledge_runtime_v1_1(runtime, blocked)


def test_v1_0_contract_and_compiler_identity_remain_separate():
    runtime_v1, _ = compile_knowledge_library(bundle_v1())
    runtime_v11, _ = compile_knowledge_library_v1_1(bundle_v1_1())

    assert runtime_v1.contract_version == "1.0.0"
    assert runtime_v1.schema_version == "1.0.0"
    assert runtime_v11.contract_version == "1.1.0"
    assert runtime_v11.schema_version == "1.1.0"
    assert json.loads(runtime_v1.canonical_json())["contract_version"] == "1.0.0"
