"""Explicit current-definition snapshots for pure domain/artifact UNIT tests only.

HTTP and repository tests use the actual database registry and explicit import.
"""

import json
from pathlib import Path

from jewelai_domain.roles import RoleProfile, RoleRegistry


def current_roles():
    source = (
        Path(__file__).parents[1] / "packages/persistence/src/jewelai_persistence/role_seed.json"
    )
    profiles = {
        r["role_id"]: RoleProfile.model_validate(dict(r, revision=1))
        for r in json.loads(source.read_text())
    }
    return RoleRegistry(lambda rid: profiles[rid], lambda: tuple(profiles.values()))
