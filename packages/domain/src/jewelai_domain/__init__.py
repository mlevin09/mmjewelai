"""Jewelry design contracts. Import concrete types from jewelai_domain.models."""

from .dictionary import (
    DICTIONARY_SCHEMA_VERSION,
    AmbiguousMatch,
    DictionaryCategory,
    DictionaryRegistry,
    ResolvedMatch,
    UnsupportedMatch,
    load_domain_dictionary,
)
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
    "DICTIONARY_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "AmbiguousMatch",
    "Design",
    "DesignRevision",
    "DictionaryCategory",
    "DictionaryRegistry",
    "RevisionConflict",
    "ResolvedMatch",
    "ROLE_SCHEMA_VERSION",
    "RoleId",
    "RoleProfile",
    "RoleRegistry",
    "UnknownRoleError",
    "UnsupportedLocaleError",
    "UnsupportedMatch",
    "confirm_field",
    "lock_field",
    "load_domain_dictionary",
    "load_role_profiles",
    "revise_design",
    "unlock_field",
]
