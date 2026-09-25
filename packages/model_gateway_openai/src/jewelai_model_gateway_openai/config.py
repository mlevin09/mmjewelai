"""Immutable non-secret OpenAI image adapter configuration."""

import re
from dataclasses import dataclass

MAX_ASSET_BYTES = 20 * 1024 * 1024
_MODEL_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


@dataclass(frozen=True)
class OpenAIImageProviderConfig:
    allowed_models: tuple[str, ...]
    timeout_seconds: float = 180
    max_output_bytes: int = MAX_ASSET_BYTES

    def __post_init__(self) -> None:
        if (
            not isinstance(self.allowed_models, tuple)
            or not self.allowed_models
            or len(set(self.allowed_models)) != len(self.allowed_models)
        ):
            raise ValueError("OpenAI allowed models must be non-empty and unique")
        if any(
            not isinstance(model, str) or len(model) > 100 or not _MODEL_ID.fullmatch(model)
            for model in self.allowed_models
        ):
            raise ValueError("OpenAI allowed model identifier is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0 < self.timeout_seconds <= 600
        ):
            raise ValueError("OpenAI timeout must be greater than zero and at most 600 seconds")
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or not 0 < self.max_output_bytes <= MAX_ASSET_BYTES
        ):
            raise ValueError("OpenAI output byte limit must be within the Asset ingestion limit")
