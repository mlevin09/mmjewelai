"""Published Asset v1 JSON Schema."""

import json
import sys
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from .models import Asset, AssetIngestionPolicy, AssetIngestionRequest, StoredObject

AssetContract = Annotated[
    Asset | AssetIngestionRequest | AssetIngestionPolicy | StoredObject,
    Field(union_mode="left_to_right"),
]


def asset_json_schema() -> dict:
    return TypeAdapter(AssetContract).json_schema()


def main() -> None:
    target = Path(sys.argv[1])
    target.write_text(json.dumps(asset_json_schema(), indent=2) + "\n")


if __name__ == "__main__":
    main()
