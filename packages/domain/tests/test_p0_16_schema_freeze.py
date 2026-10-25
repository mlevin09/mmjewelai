import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECONCILIATION = ROOT / "data" / "knowledge" / "v1" / "p0-16-source-reconciliation-1.0.0.json"
TARGET_REGISTRY = ROOT / "specs" / "jewelry-design-schema" / "target-registry-v1.1.0.json"
SCHEMA_CONTRACT = ROOT / "specs" / "jewelry-design-schema" / "contract-v1.1.0.json"
REFERENCE_SCHEMA = ROOT / "specs" / "reference-bindings" / "schema-v1.0.0.json"
VERIFICATION_SCHEMA = ROOT / "specs" / "visualization-verification" / "schema-v1.0.0.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_source_reconciliation_freezes_all_166_targets_without_reconstructed_authority():
    artifact = load(RECONCILIATION)

    assert artifact["status"] == "FROZEN_TARGET_OWNERSHIP_AND_CONTRACT_BOUNDARIES"
    assert artifact["arithmetic_reconciliation"]["final"] == 166
    assert len(artifact["targets"]) == 166
    assert len({item["target"] for item in artifact["targets"]}) == 166

    allowed = {
        "REPOSITORY_EXACT",
        "TRANSCRIPT_EXACT",
        "ARTIFACT_EXACT",
        "CANONICALIZED_FROM_EXPLICIT_SOURCE_SEMANTICS",
    }
    resolutions = {item["p0_16_resolution"] for item in artifact["targets"]}
    assert resolutions <= allowed
    assert all("RECONSTRUCTED" not in item["p0_16_resolution"] for item in artifact["targets"])
    assert artifact["decision"]["historical_hidden_id_parity_claimed"] is False


def test_v1_1_target_registry_matches_frozen_product_state_ownership():
    artifact = load(RECONCILIATION)
    registry = load(TARGET_REGISTRY)
    contract = load(SCHEMA_CONTRACT)

    expected = {
        item["target"]
        for item in artifact["targets"]
        if item["runtime_layer"] in {"CURRENT_PRODUCT_STATE_V1", "PRODUCT_STATE_VNEXT"}
    }
    actual = {item["target"] for item in registry["targets"]}

    assert expected == actual
    assert len(actual) == 148
    assert contract["current_v1_targets"] == 30
    assert contract["additive_v1_1_targets"] == 118
    assert contract["total_product_state_target_families"] == 148
    assert contract["implementation_status"] == "PENDING_P0_17"


def test_reference_binding_contract_is_frozen_and_outside_product_state():
    schema = load(REFERENCE_SCHEMA)

    assert schema["$id"] == "urn:jewelai:reference-binding:1.0.0"
    assert schema["properties"]["contract_version"]["const"] == "1.0.0"
    assert schema["$defs"]["feature_binding"]["properties"]["relation"]["enum"] == [
        "KEEP",
        "CHANGE",
        "LOCKED",
        "INSPIRATION",
        "UNKNOWN",
    ]


def test_visualization_verification_contract_is_frozen_and_preserves_p0_12_semantics():
    schema = load(VERIFICATION_SCHEMA)

    assert schema["$id"] == "urn:jewelai:visualization-verification:1.0.0"
    assert schema["properties"]["contract_version"]["const"] == "1.0.0"
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
    assert len(schema["$defs"]["check"]["properties"]["dimension"]["enum"]) == 12
