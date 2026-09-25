from uuid import UUID

import pytest
from pydantic import ValidationError

from jewelai_auth import (
    AuthenticatedPrincipal,
    AuthorizationDeniedError,
    MembershipRole,
    VerifiedIdentity,
    require_can_add_membership,
    require_can_change_membership,
    require_can_list_memberships,
    require_can_remove_membership,
)


def test_identity_and_principal_are_strict_immutable_contracts():
    identity = VerifiedIdentity(issuer="https://issuer.test", subject="subject")
    assert identity.email is None
    with pytest.raises(ValidationError):
        identity.subject = "changed"
    with pytest.raises(ValidationError):
        VerifiedIdentity(issuer=" ", subject="subject")
    principal = AuthenticatedPrincipal(principal_id=UUID(int=1))
    assert principal.model_dump() == {
        "principal_id": UUID(int=1),
        "email": None,
        "display_name": None,
    }


def test_external_identity_identifiers_are_preserved_exactly():
    identity = VerifiedIdentity(issuer="https://issuer.test", subject="alice")
    assert identity.issuer == "https://issuer.test"
    assert identity.subject == "alice"


@pytest.mark.parametrize("subject", [" alice", "alice ", " alice ", " "])
def test_subject_with_boundary_whitespace_is_rejected_not_normalized(subject):
    with pytest.raises(ValidationError, match="leading or trailing whitespace"):
        VerifiedIdentity(issuer="https://issuer.test", subject=subject)


@pytest.mark.parametrize("issuer", [" https://issuer.test", "https://issuer.test ", " "])
def test_issuer_with_boundary_whitespace_is_rejected_not_normalized(issuer):
    with pytest.raises(ValidationError, match="leading or trailing whitespace"):
        VerifiedIdentity(issuer=issuer, subject="alice")


def test_distinct_external_subject_cannot_collapse_through_normalization():
    exact = VerifiedIdentity(issuer="https://issuer.test", subject="alice")
    assert exact.subject == "alice"
    with pytest.raises(ValidationError):
        VerifiedIdentity(issuer="https://issuer.test", subject=" alice ")


@pytest.mark.parametrize("role", [MembershipRole.OWNER, MembershipRole.ADMIN])
def test_owner_and_admin_can_list_memberships(role):
    require_can_list_memberships(role)


def test_member_cannot_list_memberships():
    with pytest.raises(AuthorizationDeniedError):
        require_can_list_memberships(MembershipRole.MEMBER)


@pytest.mark.parametrize("target", list(MembershipRole))
def test_owner_can_add_any_role(target):
    require_can_add_membership(MembershipRole.OWNER, target)


def test_admin_can_only_add_and_remove_members():
    require_can_add_membership(MembershipRole.ADMIN, MembershipRole.MEMBER)
    require_can_remove_membership(MembershipRole.ADMIN, MembershipRole.MEMBER)
    for role in (MembershipRole.OWNER, MembershipRole.ADMIN):
        with pytest.raises(AuthorizationDeniedError):
            require_can_add_membership(MembershipRole.ADMIN, role)
        with pytest.raises(AuthorizationDeniedError):
            require_can_remove_membership(MembershipRole.ADMIN, role)


def test_only_owner_can_change_roles():
    require_can_change_membership(MembershipRole.OWNER, MembershipRole.MEMBER, MembershipRole.ADMIN)
    with pytest.raises(AuthorizationDeniedError):
        require_can_change_membership(
            MembershipRole.ADMIN, MembershipRole.MEMBER, MembershipRole.ADMIN
        )


def test_member_cannot_manage_memberships():
    for operation in (
        lambda: require_can_add_membership(MembershipRole.MEMBER, MembershipRole.MEMBER),
        lambda: require_can_remove_membership(MembershipRole.MEMBER, MembershipRole.MEMBER),
    ):
        with pytest.raises(AuthorizationDeniedError):
            operation()
