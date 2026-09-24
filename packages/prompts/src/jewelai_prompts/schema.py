"""Generate the Prompt Compiler v1 JSON Schema."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from .models import CompiledPrompt, PromptTemplateBundle


def prompt_json_schema() -> dict:
    return TypeAdapter(PromptTemplateBundle | CompiledPrompt).json_schema(
        ref_template="#/$defs/{model}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(prompt_json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
