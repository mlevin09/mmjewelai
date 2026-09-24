"""Published Asset Access v1 JSON Schema."""

import json
import sys
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from .access import AssetAccessPolicy, SignedAssetReadAccess

AssetAccessContract = Annotated[
    AssetAccessPolicy | SignedAssetReadAccess,
    Field(union_mode="left_to_right"),
]


def asset_access_json_schema() -> dict:
    return TypeAdapter(AssetAccessContract).json_schema()


def main() -> None:
    target = Path(sys.argv[1])
    target.write_text(json.dumps(asset_access_json_schema(), indent=2) + "\n")


if __name__ == "__main__":
    main()
