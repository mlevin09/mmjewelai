"""Current professional identities; no authorization or draft-persona instruction semantics."""

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from .models import ImmutableModel

ROLE_SCHEMA_VERSION = "1.0.0"


class RoleId(StrEnum):
    RR_C02 = "RR-C02"
    RR_C04 = "RR-C04"
    RR_C06 = "RR-C06"
    RR_C09 = "RR-C09"
    RR_C10 = "RR-C10"
    RR_C11 = "RR-C11"
    RR_C12 = "RR-C12"
    RR_C14 = "RR-C14"
    RR_C15 = "RR-C15"
    RR_C16 = "RR-C16"
    RR_C17 = "RR-C17"
    RR_C18 = "RR-C18"
    RR_C20 = "RR-C20"
    RR_C21 = "RR-C21"
    RR_C26 = "RR-C26"
    RR_C22 = "RR-C22"
    RR_C27 = "RR-C27"
    RR_C28 = "RR-C28"
    RR_C23 = "RR-C23"
    RR_C24 = "RR-C24"
    RR_C25 = "RR-C25"


class DerivationMode(StrEnum):
    SOURCED_WITH_UNCERTAINTY = "sourced_with_uncertainty"
    REQUEST_EXACT_WHEN_REQUIRED = "request_exact_when_required"


class RoleProfile(ImmutableModel):
    role_id: RoleId
    name_ru: str = Field(min_length=1)
    name_en: str | None = None
    status: Literal["active", "inactive"]
    merged_from_ids: tuple[str, ...] = ()
    role_data: dict
    revision: int = Field(ge=1)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    authorization_effect: Literal["none"] = "none"


class RoleCatalogUnavailableError(RuntimeError):
    """Current catalog cannot be read or validated; no storage detail crosses API."""


class UnknownRoleError(LookupError):
    pass


class UnsupportedLocaleError(LookupError):
    pass


class RoleRegistry(Mapping[RoleId, RoleProfile]):
    """Read current rows on every lookup; no stale role-definition cache or JSON fallback."""

    def __init__(
        self,
        resolve: Callable[[str], RoleProfile],
        list_active: Callable[[], tuple[RoleProfile, ...]],
    ):
        self._resolve = resolve
        self._list_active = list_active

    @property
    def artifact_version(self):
        # Retained opaque wire marker, never a role-definition loading pin.
        return ROLE_SCHEMA_VERSION

    def __getitem__(self, role_id):
        return self.get_profile(role_id)

    def __iter__(self) -> Iterator[RoleId]:
        return iter(p.role_id for p in self._list_active())

    def __len__(self):
        return len(self._list_active())

    def get_profile(self, role_id):
        try:
            canonical = RoleId(role_id)
        except ValueError as exc:
            raise UnknownRoleError("Unknown canonical role") from exc
        profile = self._resolve(canonical.value)
        if profile.status != "active":
            raise UnknownRoleError("Inactive role")
        return profile

    def resolve_locale(self, role_id, requested_locale):
        self.get_profile(role_id)
        locale = requested_locale.strip().lower().replace("_", "-").split("-", 1)[0]
        if locale not in {"en", "ru"}:
            raise UnsupportedLocaleError("Unsupported locale")
        return locale
