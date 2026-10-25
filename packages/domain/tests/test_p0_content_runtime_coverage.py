import json
from pathlib import Path

import pytest

from jewelai_domain.knowledge_library import (
    KnowledgeLibraryBundle,
    KnowledgeLibraryRegistry,
    KnowledgeLibraryValidationError,
    Policy,
)

ROOT = Path(__file__).resolve().parents[3]
COVERAGE = ROOT / "data" / "knowledge" / "v1" / "p0-content-runtime-coverage-1.0.0.json"
CATALOG = ROOT / "data" / "knowledge" / "v1" / "jewelry-core-1.0.0.json"


def test_p0_content_baseline_is_not_misreported_as_current_runtime_coverage():
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))

    assert coverage["status"] == "PARTIAL_BY_SCHEMA"
    assert coverage["content_baseline"]["content_governed_target_path_family_count"] == 166
    assert coverage["content_baseline"]["runtime_execution_claimed"] is False
    assert coverage["current_runtime"]["knowledge_library_policy_target_family_count"] == 30
    assert (
        coverage["content_baseline"]["content_governed_target_path_family_count"]
        > coverage["current_runtime"]["knowledge_library_policy_target_family_count"]
    )
    assert coverage["integration_layers"]["reference_semantics_p0_11"]["status"] == (
        "NOT_FULLY_REPRESENTABLE"
    )
    assert coverage["integration_layers"]["visualization_verification_p0_12"]["status"] == (
        "SEPARATE_RUNTIME_CONTRACT_REQUIRED"
    )


def test_current_contract_rejects_unversioned_p0_10_target_expansion():
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    bundle = KnowledgeLibraryBundle.model_validate(payload)
    extra = Policy(
        policy_id="POL-P0-14-UNVERSIONED-COMPOSITION",
        target="composition.symmetry",
        effect="This target intentionally demonstrates that P0-10 cannot be added silently.",
        source_kind="INTERNAL_PRODUCT_DECISION",
        source_refs=("DEC-JEWELAI-PRODUCTION-CATALOG-V1",),
        lifecycle_status="REVIEWED",
    )
    widened = bundle.model_copy(update={"policies": (*bundle.policies, extra)})

    with pytest.raises(
        KnowledgeLibraryValidationError,
        match="targets unavailable Design Schema v1 field composition.symmetry",
    ):
        KnowledgeLibraryRegistry(widened)
