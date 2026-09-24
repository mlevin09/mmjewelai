"""Export the Rules Engine v1 wire contract."""

import argparse
import json
from pathlib import Path

from .rules import RULES_SCHEMA_VERSION, RulesBundle


def rules_json_schema() -> dict:
    schema = RulesBundle.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"urn:jewelai:rules:{RULES_SCHEMA_VERSION}"
    schema["description"] = (
        "JewelAI Rules Engine v1 declarative artifact. The bounded Python interpreter owns "
        "evaluation; catalogs contain no executable expressions or user-facing wording."
    )
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(rules_json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
