"""Export the Role Profiles v1 wire contract."""

import argparse
import json
from pathlib import Path

from .roles import ROLE_POLICY_MATRIX, ROLE_SCHEMA_VERSION, RoleProfileBundle


def role_profiles_json_schema() -> dict:
    schema = RoleProfileBundle.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"urn:jewelai:role-profiles:{ROLE_SCHEMA_VERSION}"
    schema["description"] = (
        "JewelAI Role Profiles v1. Conversational policy only; roles grant no authorization "
        "and do not alter the Jewelry Design Schema or its transitions."
    )
    role_definition = schema["$defs"]["RoleProfile"]
    role_definition["allOf"] = []
    for role_id, policies in ROLE_POLICY_MATRIX.items():
        expertise, vocabulary, detail_level, derivation_mode = policies
        role_definition["allOf"].append(
            {
                "if": {
                    "properties": {"role_id": {"const": role_id.value}},
                    "required": ["role_id"],
                },
                "then": {
                    "properties": {
                        "expertise": {"const": expertise.value},
                        "vocabulary": {"const": vocabulary.value},
                        "detail_level": {"const": detail_level.value},
                        "derivation_policy": {
                            "properties": {"mode": {"const": derivation_mode.value}},
                            "required": ["mode"],
                        },
                    }
                },
            }
        )
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(role_profiles_json_schema(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
