"""Persistence boundary for immutable JewelAI domain revisions."""

from .database import create_database_engine, create_session_factory
from .models import Base
from .repository import (
    DuplicateRevisionError,
    NotFoundError,
    OwnershipMismatchError,
    PersistenceRepository,
    StaleRevisionError,
)

__all__ = [
    "Base",
    "DuplicateRevisionError",
    "NotFoundError",
    "OwnershipMismatchError",
    "PersistenceRepository",
    "StaleRevisionError",
    "create_database_engine",
    "create_session_factory",
]
