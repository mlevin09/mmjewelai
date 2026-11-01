"""Current canonical contracts; never overwrite the frozen legacy schema artifacts."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from .downstream_preparation import (
    AnyCanonicalInternalFinalPromptHandoff,
    GenerationPreparationPayload,
)
from .downstream_preparation_v2 import GenerationPreparationPayloadV2
from .enrichment import AnyPromptEnrichmentResult, StructuredPromptEnrichmentResultV2
from .final_prompt_v3 import CanonicalInternalFinalPromptHandoffV3


def canonical_json_schema() -> dict:
    return TypeAdapter(
        AnyPromptEnrichmentResult
        | AnyCanonicalInternalFinalPromptHandoff
        | GenerationPreparationPayload
        | StructuredPromptEnrichmentResultV2
        | CanonicalInternalFinalPromptHandoffV3
        | GenerationPreparationPayloadV2
    ).json_schema(ref_template="#/$defs/{model}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(canonical_json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
