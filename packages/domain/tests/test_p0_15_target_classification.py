import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET_MAP = ROOT / "data" / "knowledge" / "v1" / "p0-15-canonical-target-map-0.1.0.json"
SCHEMA_PROPOSAL = ROOT / "specs" / "jewelry-design-schema" / "vnext-proposal-0.1.0.json"
REFERENCE_SCHEMA = ROOT / "specs" / "reference-bindings" / "v1-draft.schema.json"
VERIFICATION_SCHEMA = ROOT / "specs" / "visualization-verification" / "v1-draft.schema.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_p0_15_target_accounting_is_complete_and_layered():
    artifact = load(TARGET_MAP)
    counts = artifact["counts"]

    assert counts["total"] == 166
    assert len(artifact["targets"]) == 166
    assert len({item["target"] for item in artifact["targets"]}) == 166

    by_layer = counts["by_runtime_layer"]
    assert by_layer["CURRENT_PRODUCT_STATE_V1"] == 30
    assert by_layer["PRODUCT_STATE_VNEXT"] == 118
    assert counts["not_product_state_total"] == 18
    assert sum(by_layer.values()) == 166

    assert artifact["freeze_gate"]["normative_schema_freeze_allowed"] is False


def test_non_product_state_layers_stay_out_of_schema_proposal():
    artifact = load(TARGET_MAP)
    proposal = load(SCHEMA_PROPOSAL)

    product_targets = {
        item["target"]
        for item in artifact["targets"]
        if item["runtime_layer"] == "PRODUCT_STATE_VNEXT"
    }
    excluded = {
        target
        for values in proposal["excluded_from_product_state"].values()
        for target in values
    }

    assert proposal["candidate_product_state_vnext_target_count"] == len(product_targets)
    assert len(product_targets) == 118
    assert product_targets.isdisjoint(excluded)

    assert "references.feature_bindings" in excluded
    assert "verification.geometry_plausibility" in excluded
    assert "presentation.camera_view" in excluded
    assert "creative_intent_raw" in excluded
    assert "proportions.relative_ratios" in excluded


def test_reference_binding_contract_preserves_p0_11_relations():
    schema = load(REFERENCE_SCHEMA)
    relation = schema["$defs"]["feature_binding"]["properties"]["relation"]["enum"]

    assert relation == ["KEEP", "CHANGE", "LOCKED", "INSPIRATION", "UNKNOWN"]
    assert "asset_id" in schema["required"]
    assert "feature_bindings" in schema["required"]


def test_verification_contract_preserves_p0_12_states_and_actions():
    schema = load(VERIFICATION_SCHEMA)

    assert schema["properties"]["overall_status"]["enum"] == [
        "PASS",
        "FAIL",
        "UNVERIFIABLE",
        "NOT_APPLICABLE",
    ]
    assert schema["properties"]["action"]["enum"] == [
        "ACCEPT",
        "RETRY",
        "ASK",
        "CAD_3D_FALLBACK",
        "DO_NOT_CLAIM",
    ]
    dimensions = schema["$defs"]["check"]["properties"]["dimension"]["enum"]
    assert len(dimensions) == 12
    assert "edit_identity_preservation" in dimensions
    assert "cross_view_consistency" in dimensions
