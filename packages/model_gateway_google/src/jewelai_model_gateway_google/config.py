"""Immutable non-secret Google Generative Language image configuration."""

from dataclasses import dataclass

GOOGLE_PROVIDER_ID = "google"
GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
GOOGLE_IMAGE_MODELS = frozenset(
    {
        "gemini-3.1-flash-lite-image",
        "gemini-3.1-flash-image",
        "gemini-3-pro-image",
    }
)
MAX_ASSET_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class GoogleGenerativeLanguageConfig:
    allowed_models: tuple[str, ...]
    timeout_seconds: float = 180
    max_output_bytes: int = MAX_ASSET_BYTES

    def __post_init__(self) -> None:
        if (
            not isinstance(self.allowed_models, tuple)
            or not self.allowed_models
            or len(set(self.allowed_models)) != len(self.allowed_models)
            or any(model not in GOOGLE_IMAGE_MODELS for model in self.allowed_models)
        ):
            raise ValueError(
                "Google allowed models must be a non-empty unique subset of the supported "
                "image models"
            )
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int | float)
            or not 0 < self.timeout_seconds <= 600
        ):
            raise ValueError("Google timeout must be greater than zero and at most 600 seconds")
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or not 0 < self.max_output_bytes <= MAX_ASSET_BYTES
        ):
            raise ValueError("Google output byte limit must be within the Asset ingestion limit")
