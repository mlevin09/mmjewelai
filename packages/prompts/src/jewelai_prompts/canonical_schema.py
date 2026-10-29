"""Current canonical contracts; never overwrite the frozen legacy schema artifacts."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from .downstream_preparation import (
    AnyCanonicalInternalFinalPromptHandoff,
    GenerationPreparationPayload,
)
from .enrichment import AnyPromptEnrichmentResult


def canonical_json_schema() -> dict:
    return TypeAdapter(
        AnyPromptEnrichmentResult
        | AnyCanonicalInternalFinalPromptHandoff
        | GenerationPreparationPayload
    ).json_schema(ref_template="#/$defs/{model}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(canonical_json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
