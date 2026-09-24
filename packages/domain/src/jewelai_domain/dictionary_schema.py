"""Export the Domain Dictionary v1 wire contract."""

import argparse
import json
from pathlib import Path

from .dictionary import DICTIONARY_SCHEMA_VERSION, DictionaryBundle


def dictionary_json_schema() -> dict:
    schema = DictionaryBundle.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"urn:jewelai:domain-dictionary:{DICTIONARY_SCHEMA_VERSION}"
    schema["description"] = (
        "JewelAI Domain Dictionary v1. Vocabulary and exact normalization only; it contains no "
        "gemstone dimensions, manufacturing estimates, rules, or authorization semantics."
    )
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(dictionary_json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
