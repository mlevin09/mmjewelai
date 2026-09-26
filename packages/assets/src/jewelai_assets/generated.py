"""Stable generated-output identity shared by execution and maintenance."""

from uuid import UUID, uuid5

GENERATED_ASSET_NAMESPACE = UUID("7254a3d8-cb6c-5df0-89c4-d8028f63cd85")


def generated_asset_id(generation_run_id: UUID, ordinal: int) -> UUID:
    """Derive the historical UUIDv5 identity from immutable run/ordinal lineage."""
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not 1 <= ordinal <= 4:
        raise ValueError("Generation output ordinal must be between 1 and 4")
    return uuid5(GENERATED_ASSET_NAMESPACE, f"{generation_run_id}:{ordinal}")
