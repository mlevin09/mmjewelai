import json
from pathlib import Path

from jsonschema import Draft202012Validator

from jewelai_prompts.canonical_schema import canonical_json_schema


def test_current_and_historical_contract_schema_drift():
    generated = canonical_json_schema()
    Draft202012Validator.check_schema(generated)
    root = Path(__file__).resolve().parents[3]
    assert generated == json.loads(
        (root / "specs/prompts/canonical-preparation-schema.json").read_text()
    )
    definitions = generated["$defs"]
    assert "compiled_prompt" not in definitions["StructuredPromptEnrichmentResult"]["properties"]
    assert (
        definitions["PromptEnrichmentResult"]["properties"]["enrichment_version"]["const"]
        == "1.2.0"
    )
