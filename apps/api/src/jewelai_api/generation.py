"""Trusted server-side generation profile configuration."""

from types import MappingProxyType
from typing import Annotated

from jewelai_model_gateway import GenerationConfiguration
from pydantic import BaseModel, ConfigDict, StringConstraints

ProfileId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
Version = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


class GenerationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: ProfileId
    profile_version: Version
    provider: ProfileId
    model: ProfileId
    configuration: GenerationConfiguration


class UnknownGenerationProfileError(LookupError):
    pass


class GenerationProfileRegistry:
    def __init__(self, profiles: tuple[GenerationProfile, ...] = ()):
        by_id = {item.profile_id: item for item in profiles}
        if len(by_id) != len(profiles):
            raise ValueError("Generation profile IDs must be unique")
        self._profiles = MappingProxyType(by_id)

    def get(self, profile_id: str) -> GenerationProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise UnknownGenerationProfileError(
                f"Unknown or unavailable generation profile: {profile_id}"
            ) from exc
