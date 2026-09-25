"""Provider-neutral JewelAI authentication boundary."""

from .contracts import AuthenticatedPrincipal, MembershipRole, TokenVerifier, VerifiedIdentity
from .errors import (
    AuthenticationError,
    AuthenticationUnavailableError,
    AuthorizationDeniedError,
    LastOwnerError,
    MembershipConflictError,
    MembershipNotFoundError,
)
from .policy import (
    require_can_add_membership,
    require_can_change_membership,
    require_can_list_memberships,
    require_can_remove_membership,
)

__all__ = [
    "AuthenticatedPrincipal",
    "AuthenticationError",
    "AuthenticationUnavailableError",
    "AuthorizationDeniedError",
    "LastOwnerError",
    "MembershipConflictError",
    "MembershipNotFoundError",
    "MembershipRole",
    "TokenVerifier",
    "VerifiedIdentity",
    "require_can_add_membership",
    "require_can_change_membership",
    "require_can_list_memberships",
    "require_can_remove_membership",
]
