"""Provider-neutral identity and organization membership contracts."""

from enum import StrEnum
from typing import Annotated, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

Issuer = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Subject = Annotated[str, StringConstraints(min_length=1, max_length=255)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=320)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class VerifiedIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: Issuer
    subject: Subject
    email: Email | None = None
    display_name: DisplayName | None = None

    @field_validator("issuer", "subject")
    @classmethod
    def security_identifiers_are_exact(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Security identifiers must not have leading or trailing whitespace")
        return value


class AuthenticatedPrincipal(BaseModel):
    """JewelAI-facing request identity; external identifiers stay private."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: UUID
    email: Email | None = None
    display_name: DisplayName | None = None


@runtime_checkable
class TokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedIdentity: ...
