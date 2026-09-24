"""Generate the published Parser Proposal v1 JSON Schema."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from .models import ParserCandidate, ParserProposal


def parser_json_schema() -> dict:
    return TypeAdapter(ParserCandidate | ParserProposal).json_schema(ref_template="#/$defs/{model}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(parser_json_schema(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
