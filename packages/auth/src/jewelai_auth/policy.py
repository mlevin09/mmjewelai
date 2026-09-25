"""Pure deterministic organization membership-management policy."""

from .contracts import MembershipRole
from .errors import AuthorizationDeniedError


def require_can_list_memberships(actor: MembershipRole) -> None:
    if actor not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise AuthorizationDeniedError("Membership role cannot list organization memberships")


def require_can_add_membership(actor: MembershipRole, target: MembershipRole) -> None:
    if actor is MembershipRole.OWNER:
        return
    if actor is MembershipRole.ADMIN and target is MembershipRole.MEMBER:
        return
    raise AuthorizationDeniedError("Membership role cannot add the requested organization role")


def require_can_change_membership(
    actor: MembershipRole, current: MembershipRole, target: MembershipRole
) -> None:
    if actor is not MembershipRole.OWNER:
        raise AuthorizationDeniedError("Membership role cannot change organization roles")


def require_can_remove_membership(actor: MembershipRole, target: MembershipRole) -> None:
    if actor is MembershipRole.OWNER:
        return
    if actor is MembershipRole.ADMIN and target is MembershipRole.MEMBER:
        return
    raise AuthorizationDeniedError("Membership role cannot remove the requested organization role")
