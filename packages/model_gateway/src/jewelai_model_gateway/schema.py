"""Generate the Model Gateway v1 JSON Schema."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from .models import GenerationRequest, GenerationResult, GenerationRun


def model_gateway_json_schema() -> dict:
    return TypeAdapter(GenerationRequest | GenerationResult | GenerationRun).json_schema(
        ref_template="#/$defs/{model}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(model_gateway_json_schema(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
