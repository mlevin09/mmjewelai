"""Persistence boundary for immutable JewelAI domain revisions."""

from .database import create_database_engine, create_session_factory
from .models import (
    AssetRow,
    AuthPrincipalRow,
    Base,
    GenerationDispatchOutboxRow,
    OrganizationMembershipRow,
)
from .repository import (
    DuplicateRevisionError,
    GenerationStateConflictError,
    NotFoundError,
    OwnershipMismatchError,
    PersistenceRepository,
    StaleRevisionError,
)

__all__ = [
    "Base",
    "AssetRow",
    "AuthPrincipalRow",
    "DuplicateRevisionError",
    "GenerationStateConflictError",
    "GenerationDispatchOutboxRow",
    "NotFoundError",
    "OwnershipMismatchError",
    "OrganizationMembershipRow",
    "PersistenceRepository",
    "StaleRevisionError",
    "create_database_engine",
    "create_session_factory",
]
