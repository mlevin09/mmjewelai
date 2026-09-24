"""Export the Question Catalog v1 wire contract."""

import argparse
import json
from pathlib import Path

from .questions import QUESTION_SCHEMA_VERSION, QuestionCatalogBundle


def question_catalog_json_schema() -> dict:
    schema = QuestionCatalogBundle.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"urn:jewelai:question-catalog:{QUESTION_SCHEMA_VERSION}"
    schema["description"] = (
        "JewelAI Question Catalog v1. Semantic question contracts and presentation only; "
        "it contains no selection, sequencing, readiness, derivation, or authorization logic."
    )
    return schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(question_catalog_json_schema(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
