"""Immutable non-secret text-understanding configuration."""

import re
from dataclasses import dataclass

GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


@dataclass(frozen=True)
class GoogleTextUnderstandingConfig:
    model: str
    timeout_seconds: float = 30
    max_response_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        if (
            not isinstance(self.model, str)
            or not self.model
            or self.model != self.model.strip()
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,119}", self.model) is None
        ):
            raise ValueError("Google text-understanding model must be an exact bounded model ID")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0 < self.timeout_seconds <= 120
        ):
            raise ValueError("Text-understanding timeout must be greater than zero and at most 120")
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or not 1024 <= self.max_response_bytes <= 1024 * 1024
        ):
            raise ValueError("Text-understanding response limit must be between 1 KiB and 1 MiB")
