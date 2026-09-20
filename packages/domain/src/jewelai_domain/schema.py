"""Export the wire contract without importing API, storage or provider code."""

import argparse
import json
from pathlib import Path

from .models import DesignRevision


def json_schema() -> dict:
    schema = DesignRevision.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:jewelai:design-revision:1.0.0"
    schema["description"] = (
        "Jewelry Design Schema v1. Snapshot structure only; Python semantic validation and "
        "revision transitions are also required. See the accompanying specification."
    )
    schema["allOf"] = [
        {
            "if": {"properties": {"revision": {"const": 1}}, "required": ["revision"]},
            "then": {
                "properties": {
                    "parent_revision_id": {"type": "null"},
                    "event": {"properties": {"action": {"const": "create"}}},
                }
            },
            "else": {
                "required": ["parent_revision_id"],
                "properties": {
                    "parent_revision_id": {"type": "string", "format": "uuid"},
                    "event": {"properties": {"action": {"not": {"const": "create"}}}},
                },
            },
        }
    ]
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
