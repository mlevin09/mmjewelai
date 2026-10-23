"""Generate the Step #12 provider-neutral output JSON Schema."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from .final_prompt import FinalPromptAssembly


def internal_final_prompt_json_schema() -> dict:
    schema = TypeAdapter(FinalPromptAssembly).json_schema(ref_template="#/$defs/{model}")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:jewelai:prompt-enrichment-final-output:1.0.0"
    return schema


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(internal_final_prompt_json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
