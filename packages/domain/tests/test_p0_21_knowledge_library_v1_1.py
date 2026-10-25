import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from jewelai_domain.knowledge_activation import (
    REQUIRED_PRODUCTION_VALIDATION_CHECKS,
    ProductionValidationCheck,
)
from jewelai_domain.knowledge_activation_v1_1 import (
    ProductionValidationReportV1_1,
    promote_knowledge_runtime_v1_1,
)
from jewelai_domain.knowledge_library import (
    KnowledgeLibraryValidationError,
    validate_knowledge_library,
)
from jewelai_domain.knowledge_library_v1_1 import (
    KnowledgeLibraryV1_1ValidationError,
    compile_knowledge_library_v1_1,
    validate_knowledge_library_v1_1,
)
from jewelai_domain.knowledge_policy import (
    KnowledgePolicyEngine,
    build_knowledge_runtime_state,
)
from jewelai_domain.knowledge_qualification import (
    KnowledgeReleaseCandidateKind,
    KnowledgeReleaseCandidateSelection,
    KnowledgeReleaseQualificationStatus,
)
from jewelai_domain.knowledge_qualification_v1_1 import qualify_knowledge_release_v1_1
from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
from jewelai_domain.models import Design, DesignRevision, MessageSource, RevisionEvent
from jewelai_domain.models_v1_1 import upgrade_design_revision_v1_to_v1_1

NOW = datetime(2026, 10, 25, 18, 0, tzinfo=UTC)
SOURCE = MessageSource(message_id="p0-21", recorded_at=NOW)


def bundle_v1_1():
    return {
        "contract_version": "1.1.0",
        "package_id": "jewelai.test.v1_1",
        "artifact_version": "1.0.0",
        "sources": [
            {
                "source_id": "DEC-P0-21",
                "title": "P0-21 runtime decision",
                "source_type": "INTERNAL_DECISION",
                "language": "not_applicable",
                "evidence_tier": "INTERNAL",
                "lifecycle_status": "REVIEWED",
            }
        ],
        "claims": [],
        "domain_knowledge": [],
        "language_mappings": [],
        "policies": [
            {
                "policy_id": "POL-COMPOSITION",
                "target": "composition.symmetry_mode",
                "effect": "Preserve explicit composition symmetry state.",
                "source_kind": "INTERNAL_PRODUCT_DECISION",
                "source_refs": ["DEC-P0-21"],
                "lifecycle_status": "REVIEWED",
            },
            {
                "policy_id": "POL-COMPONENT-MATERIAL",
                "target": "metal.components.{component_id}.material",
                "effect": "Respect explicit material state for a stable metal component.",
                "source_kind": "INTERNAL_PRODUCT_DECISION",
                "source_refs": ["DEC-P0-21"],
                "lifecycle_status": "REVIEWED",
            },
        ],
    }


def revision_v1_1():
    v1 = DesignRevision(
        schema_version="1.0.0",
        design_id=UUID("21212121-2121-4212-8212-212121212121"),
        revision_id=UUID("31313131-3131-4313-8313-313131313131"),
        revision=1,
        parent_revision_id=None,
        created_at=NOW,
        event=RevisionEvent(action="create", source=SOURCE, reason="P0-21 test"),
        design=Design(),
    )
    upgraded = upgrade_design_revision_v1_to_v1_1(v1)
    data = upgraded.design.model_dump(mode="json")
    data["composition"] = {
        "availability": "value",
        "origin": "explicit",
        "value": {
            "symmetry_mode": {
                "availability": "value",
                "origin": "explicit",
                "value": "asymmetrical",
                "source": SOURCE.model_dump(mode="json"),
                "confirmed": False,
                "locked": False,
            }
        },
        "source": SOURCE.model_dump(mode="json"),
        "confirmed": False,
        "locked": False,
    }
    return upgraded.model_copy(update={"design": type(upgraded.design).model_validate(data)})


def report(runtime):
    return ProductionValidationReportV1_1(
        package_id=runtime.package_id,
        artifact_version=runtime.artifact_version,
        runtime_sha256=runtime.sha256,
        checks=tuple(
            ProductionValidationCheck(
                name=name,
                outcome="PASS",
                evidence_ref=f"ci://p0-21/{name}",
            )
            for name in REQUIRED_PRODUCTION_VALIDATION_CHECKS
        ),
    )


def test_v1_1_accepts_new_policy_targets_without_widening_v1_contract():
    payload = bundle_v1_1()
    registry = validate_knowledge_library_v1_1(payload)
    runtime, manifest = compile_knowledge_library_v1_1(registry)

    assert runtime.contract_version == "1.1.0"
    assert runtime.schema_version == "1.1.0"
    assert manifest.runtime_sha256 == runtime.sha256
    assert {item.target for item in runtime.policies} == {
        "composition.symmetry_mode",
        "metal.components.{component_id}.material",
    }

    legacy = {**payload, "contract_version": "1.0.0"}
    with pytest.raises((KnowledgeLibraryValidationError, ValueError)):
        validate_knowledge_library(legacy)


def test_v1_1_policy_engine_matches_new_target_template_and_projects_state():
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1())
    revision = revision_v1_1()
    engine = KnowledgePolicyEngine(runtime)

    state = build_knowledge_runtime_state(runtime, revision)

    assert state.get("composition.symmetry_mode").value == "asymmetrical"
    policies = engine.policies_for("composition.symmetry_mode")
    assert tuple(item.policy_id for item in policies) == ("POL-COMPOSITION",)


def test_v1_1_activation_requires_complete_pass_evidence():
    runtime, _ = compile_knowledge_library_v1_1(bundle_v1_1())
    validation = report(runtime)
    active = promote_knowledge_runtime_v1_1(runtime, validation)

    assert active.contract_version == "1.1.0"
    assert active.runtime_sha256 == runtime.sha256
    assert active.validation_report_sha256 == validation.sha256
    assert active.active_for_production is True


def test_v1_1_storage_round_trip_and_active_load(tmp_path):
    payload = bundle_v1_1()
    runtime, _ = compile_knowledge_library_v1_1(payload)
    validation = report(runtime)
    active = promote_knowledge_runtime_v1_1(runtime, validation)
    store = KnowledgeArtifactStoreV1_1(tmp_path)

    stored = store.publish(payload)
    restored = store.load_active_runtime(
        stored.package_id,
        stored.artifact_version,
        active_release=active,
        validation_report=validation,
    )

    assert restored.compiled_runtime == runtime
    assert restored.runtime_sha256 == stored.runtime_sha256


def test_v1_1_rejects_unknown_policy_target():
    payload = json.loads(json.dumps(bundle_v1_1()))
    payload["policies"][0]["target"] = "unknown.future.field"

    with pytest.raises(
        KnowledgeLibraryV1_1ValidationError,
        match="unavailable Design Schema v1.1 field",
    ):
        validate_knowledge_library_v1_1(payload)


def test_v1_1_release_qualification_uses_v1_1_loader(tmp_path):
    payload = bundle_v1_1()
    runtime, _ = compile_knowledge_library_v1_1(payload)
    validation = report(runtime)
    active = promote_knowledge_runtime_v1_1(runtime, validation)
    store = KnowledgeArtifactStoreV1_1(tmp_path)
    stored = store.publish(payload)

    result = qualify_knowledge_release_v1_1(
        store,
        KnowledgeReleaseCandidateSelection(
            package_id=stored.package_id,
            artifact_version=stored.artifact_version,
            kind=KnowledgeReleaseCandidateKind.SYNTHETIC,
        ),
        active_release=active,
        validation_report=validation,
        source_commit="abcdef1",
    )

    assert result.status == KnowledgeReleaseQualificationStatus.QUALIFIED
    assert result.runtime_loader_compatible is True
    assert result.runtime_sha256 == runtime.sha256
