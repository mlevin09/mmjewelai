"""Jewelry design contracts. Import concrete types from jewelai_domain.models."""

from .models import SCHEMA_VERSION, Design, DesignRevision
from .revisions import RevisionConflict, confirm_field, lock_field, revise_design, unlock_field
from .roles import (
    ROLE_SCHEMA_VERSION,
    RoleId,
    RoleProfile,
    RoleRegistry,
    UnknownRoleError,
    UnsupportedLocaleError,
    load_role_profiles,
)

__all__ = [
    "SCHEMA_VERSION",
    "Design",
    "DesignRevision",
    "RevisionConflict",
    "ROLE_SCHEMA_VERSION",
    "RoleId",
    "RoleProfile",
    "RoleRegistry",
    "UnknownRoleError",
    "UnsupportedLocaleError",
    "confirm_field",
    "lock_field",
    "load_role_profiles",
    "revise_design",
    "unlock_field",
]
