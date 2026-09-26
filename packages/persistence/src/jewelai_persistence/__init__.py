"""Persistence boundary for immutable JewelAI domain revisions."""

from .database import create_database_engine, create_session_factory
from .models import (
    AssetRow,
    AuthPrincipalRow,
    Base,
    GenerationDispatchOutboxRow,
    OrganizationMembershipRow,
)
from .recovery import (
    DEFAULT_STALE_AFTER_SECONDS,
    MAX_RECOVERY_BATCH_SIZE,
    MAX_STALE_AFTER_SECONDS,
    MIN_STALE_AFTER_SECONDS,
    StaleGenerationRecoverySummary,
    recover_stale_generation_runs,
)
from .repository import (
    DuplicateRevisionError,
    GenerationRetryCreation,
    GenerationRetryNotAllowedError,
    GenerationStateConflictError,
    NotFoundError,
    OwnershipMismatchError,
    PersistenceRepository,
    StaleGenerationRunCandidate,
    StaleRevisionError,
)

__all__ = [
    "Base",
    "AssetRow",
    "AuthPrincipalRow",
    "DuplicateRevisionError",
    "DEFAULT_STALE_AFTER_SECONDS",
    "GenerationRetryCreation",
    "GenerationRetryNotAllowedError",
    "GenerationStateConflictError",
    "GenerationDispatchOutboxRow",
    "NotFoundError",
    "MAX_RECOVERY_BATCH_SIZE",
    "MAX_STALE_AFTER_SECONDS",
    "MIN_STALE_AFTER_SECONDS",
    "OwnershipMismatchError",
    "OrganizationMembershipRow",
    "PersistenceRepository",
    "StaleGenerationRunCandidate",
    "StaleGenerationRecoverySummary",
    "StaleRevisionError",
    "create_database_engine",
    "create_session_factory",
    "recover_stale_generation_runs",
]
