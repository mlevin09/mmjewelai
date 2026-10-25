"""Export Jewelry Design Schema v1.1.0 without API/storage/provider code."""

import argparse
import json
from pathlib import Path

from .models_v1_1 import DesignRevisionV1_1


def json_schema_v1_1() -> dict:
    schema = DesignRevisionV1_1.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:jewelai:design-revision:1.1.0"
    schema["description"] = (
        "Jewelry Design Schema v1.1.0 additive snapshot contract. "
        "Existing v1.0.0 snapshots remain immutable historical artifacts; "
        "reference bindings and visualization verification remain separate contracts."
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {"revision": {"const": 1}},
                "required": ["revision"],
            },
            "then": {
                "properties": {
                    "parent_revision_id": {"type": "null"},
                    "event": {
                        "properties": {"action": {"const": "create"}}
                    },
                }
            },
            "else": {
                "required": ["parent_revision_id"],
                "properties": {
                    "parent_revision_id": {
                        "type": "string",
                        "format": "uuid",
                    },
                    "event": {
                        "properties": {
                            "action": {"not": {"const": "create"}}
                        }
                    },
                },
            },
        }
    ]
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(json_schema_v1_1(), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
