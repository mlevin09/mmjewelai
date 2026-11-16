"""Export the Role Profiles v1 wire contract."""

import argparse
import json
from pathlib import Path

from .roles import RoleProfile


def role_profiles_json_schema() -> dict:
    schema = RoleProfile.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:jewelai:current-role-definition"
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
