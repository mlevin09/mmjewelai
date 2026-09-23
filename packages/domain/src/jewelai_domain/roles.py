"""Versioned conversational role policies with no authorization semantics."""

import json
from collections.abc import Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from .models import SCHEMA_VERSION, ImmutableModel, Version

ROLE_SCHEMA_VERSION = "1.0.0"


class RoleId(StrEnum):
    RETAIL_CLIENT = "retail_client"
    SALES_MANAGER = "sales_manager"
    BUYER = "buyer"
    MARKETING = "marketing"
    JEWELRY_DESIGNER = "jewelry_designer"
    INDUSTRIAL_DESIGNER = "industrial_designer"


class ExpertiseProfile(StrEnum):
    CONSUMER = "consumer"
    COMMERCIAL = "commercial"
    PROCUREMENT = "procurement"
    MARKETING_COMMUNICATION = "marketing_communication"
    JEWELRY_DESIGN = "jewelry_design"
    INDUSTRIAL_DESIGN = "industrial_design"


class VocabularyMode(StrEnum):
    PLAIN = "plain"
    COMMERCIAL = "commercial"
    SPECIFICATION = "specification"
    STORYTELLING = "storytelling"
    PROFESSIONAL_DESIGN = "professional_design"
    TECHNICAL_ENGINEERING = "technical_engineering"


class DetailLevel(StrEnum):
    ESSENTIAL = "essential"
    OPERATIONAL = "operational"
    SPECIFICATION = "specification"
    COMMUNICATION = "communication"
    PROFESSIONAL = "professional"
    ENGINEERING = "engineering"


class DerivationMode(StrEnum):
    SOURCED_WITH_UNCERTAINTY = "sourced_with_uncertainty"
    REQUEST_EXACT_WHEN_REQUIRED = "request_exact_when_required"


class QuestionPolicy(ImmutableModel):
    selection: Literal["deterministic_rules"] = "deterministic_rules"
    missing_information: Literal["ask_before_assume"] = "ask_before_assume"
    budget: Literal["product_review_required"] = "product_review_required"


class DefaultPolicy(ImmutableModel):
    mode: Literal["no_unapproved_defaults"] = "no_unapproved_defaults"


class DerivationPolicy(ImmutableModel):
    mode: DerivationMode
    provenance: Literal["required"] = "required"
    uncertainty: Literal["required_for_derived_values"] = "required_for_derived_values"


class LocalePolicy(ImmutableModel):
    supported: tuple[Literal["en", "ru"], ...]
    fallback: Literal["base_language_then_reject"] = "base_language_then_reject"
    scope_status: Literal["proposed_pending_domain_review"] = "proposed_pending_domain_review"

    @model_validator(mode="after")
    def validate_supported_locales(self):
        if not self.supported:
            raise ValueError("At least one locale must be supported")
        if len(set(self.supported)) != len(self.supported):
            raise ValueError("Supported locales must be unique")
        if tuple(sorted(self.supported)) != self.supported:
            raise ValueError("Supported locales must use stable sorted order")
        return self


ROLE_POLICY_MATRIX = {
    RoleId.RETAIL_CLIENT: (
        ExpertiseProfile.CONSUMER,
        VocabularyMode.PLAIN,
        DetailLevel.ESSENTIAL,
        DerivationMode.SOURCED_WITH_UNCERTAINTY,
    ),
    RoleId.SALES_MANAGER: (
        ExpertiseProfile.COMMERCIAL,
        VocabularyMode.COMMERCIAL,
        DetailLevel.OPERATIONAL,
        DerivationMode.SOURCED_WITH_UNCERTAINTY,
    ),
    RoleId.BUYER: (
        ExpertiseProfile.PROCUREMENT,
        VocabularyMode.SPECIFICATION,
        DetailLevel.SPECIFICATION,
        DerivationMode.SOURCED_WITH_UNCERTAINTY,
    ),
    RoleId.MARKETING: (
        ExpertiseProfile.MARKETING_COMMUNICATION,
        VocabularyMode.STORYTELLING,
        DetailLevel.COMMUNICATION,
        DerivationMode.SOURCED_WITH_UNCERTAINTY,
    ),
    RoleId.JEWELRY_DESIGNER: (
        ExpertiseProfile.JEWELRY_DESIGN,
        VocabularyMode.PROFESSIONAL_DESIGN,
        DetailLevel.PROFESSIONAL,
        DerivationMode.SOURCED_WITH_UNCERTAINTY,
    ),
    RoleId.INDUSTRIAL_DESIGNER: (
        ExpertiseProfile.INDUSTRIAL_DESIGN,
        VocabularyMode.TECHNICAL_ENGINEERING,
        DetailLevel.ENGINEERING,
        DerivationMode.REQUEST_EXACT_WHEN_REQUIRED,
    ),
}


class RoleProfile(ImmutableModel):
    schema_version: Literal["1.0.0"]
    artifact_version: Version
    role_id: RoleId
    design_schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    expertise: ExpertiseProfile
    vocabulary: VocabularyMode
    detail_level: DetailLevel
    question_policy: QuestionPolicy
    default_policy: DefaultPolicy
    derivation_policy: DerivationPolicy
    locale_policy: LocalePolicy
    authorization_effect: Literal["none"] = "none"

    @model_validator(mode="after")
    def validate_canonical_policy(self):
        actual = (
            self.expertise,
            self.vocabulary,
            self.detail_level,
            self.derivation_policy.mode,
        )
        if actual != ROLE_POLICY_MATRIX[self.role_id]:
            raise ValueError(f"Policy combination is not valid for role {self.role_id.value}")
        return self


class RoleProfileBundle(ImmutableModel):
    schema_version: Literal["1.0.0"]
    artifact_version: Version
    review_status: Literal["proposed_pending_domain_review"]
    source: Literal["docs/product/issues/02-roles.md"]
    profiles: tuple[RoleProfile, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_complete_registry(self):
        ids = [profile.role_id for profile in self.profiles]
        if len(set(ids)) != len(ids):
            raise ValueError("Role IDs must be unique")
        if set(ids) != set(RoleId):
            missing = sorted(role.value for role in set(RoleId) - set(ids))
            extra = sorted(role.value for role in set(ids) - set(RoleId))
            raise ValueError(f"Role registry must be canonical; missing={missing}, extra={extra}")
        if tuple(ids) != tuple(RoleId):
            raise ValueError("Role profiles must use canonical stable order")
        if any(profile.artifact_version != self.artifact_version for profile in self.profiles):
            raise ValueError("Every profile must match the bundle artifact version")
        return self


class UnknownRoleError(LookupError):
    """Raised when a caller requests a role outside the canonical registry."""


class UnsupportedLocaleError(LookupError):
    """Raised when neither a requested locale nor its base language is supported."""


class RoleRegistry(Mapping[RoleId, RoleProfile]):
    """Immutable lookup over one validated, complete role-profile bundle."""

    def __init__(self, bundle: RoleProfileBundle):
        bundle = RoleProfileBundle.model_validate(bundle)
        self._bundle = bundle
        self._profiles = MappingProxyType({profile.role_id: profile for profile in bundle.profiles})

    @property
    def artifact_version(self) -> str:
        return self._bundle.artifact_version

    def __getitem__(self, role_id: RoleId) -> RoleProfile:
        return self._profiles[role_id]

    def __iter__(self) -> Iterator[RoleId]:
        return iter(self._profiles)

    def __len__(self) -> int:
        return len(self._profiles)

    def get_profile(self, role_id: RoleId | str) -> RoleProfile:
        try:
            canonical = RoleId(role_id)
        except ValueError as exc:
            raise UnknownRoleError(f"Unknown canonical role: {role_id}") from exc
        return self._profiles[canonical]

    def resolve_locale(self, role_id: RoleId | str, requested_locale: str) -> str:
        profile = self.get_profile(role_id)
        normalized = requested_locale.strip().lower().replace("_", "-")
        if normalized in profile.locale_policy.supported:
            return normalized
        base = normalized.split("-", maxsplit=1)[0]
        if base in profile.locale_policy.supported:
            return base
        raise UnsupportedLocaleError(
            f"Unsupported locale {requested_locale!r} for role {profile.role_id.value}"
        )


def load_role_profiles(path: str | Path) -> RoleRegistry:
    """Load a complete registry from an explicit path; never depend on the current directory."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RoleRegistry(RoleProfileBundle.model_validate(data))
