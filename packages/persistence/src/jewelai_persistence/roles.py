"""Current PostgreSQL Roles catalog and explicit, transactional source import."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from jewelai_domain.roles import (
    RoleCatalogUnavailableError,
    RoleId,
    RoleProfile,
    RoleRegistry,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .models import RoleRow


def validate_definition(record):
    profile = RoleProfile.model_validate(record)
    for key in ("registry", "passport"):
        source = profile.role_data.get(key)
        if source is None and key == "passport":
            continue
        if (
            not isinstance(source, dict)
            or hashlib.sha256(source["content"].encode()).hexdigest() != source["sha256"]
        ):
            raise ValueError("Invalid role source integrity")
    if "conversation_policy" in profile.role_data:
        raise ValueError("No approved role-specific conversation policy is supplied")
    if profile.role_data["registry"]["maturity"] != "OWNER_CONFIRMED_COMPOSITION":
        raise ValueError("Registry composition requires approved source metadata")
    if not profile.role_data.get("registry_entry", "").startswith(f"| {profile.role_id.value} |"):
        raise ValueError("Registry identity mismatch")
    if len(set(profile.merged_from_ids)) != len(profile.merged_from_ids):
        raise ValueError("Merged identifiers must be unique metadata")
    for alias in profile.merged_from_ids:
        if alias in {r.value for r in RoleId}:
            raise ValueError("Active role cannot be a merged alias")
    personas = profile.role_data.get("personas", [])
    if "passport" in profile.role_data:
        if len(personas) != 4 or {p["persona_id"] for p in personas} != {
            f"{profile.role_id.value}/P{i}" for i in range(1, 5)
        }:
            raise ValueError("Incomplete draft personas")
        if profile.role_data["passport"]["maturity"] != "DRAFT_NOT_OWNER_APPROVED":
            raise ValueError("Passport maturity changed without approved source")
    elif personas:
        raise ValueError("Personas require source passport")
    if any(p["maturity"] != "PROTO_PERSONA_MODELING_HYPOTHESIS" for p in personas):
        raise ValueError("Unverified persona authority")
    if profile.role_data.get("authorization_effect") != "none":
        raise ValueError("Professional role cannot grant authorization")
    return profile


def _profile(row):
    return validate_definition(
        {
            k: getattr(row, k)
            for k in (
                "role_id",
                "name_ru",
                "name_en",
                "status",
                "merged_from_ids",
                "role_data",
                "revision",
                "created_at",
                "updated_at",
            )
        }
    )


def database_role_registry(factory):
    def resolve(role_id):
        try:
            with factory() as db:
                row = db.get(RoleRow, role_id)
                if row is None:
                    raise RoleCatalogUnavailableError("Current role catalog is incomplete")
                return _profile(row)
        except (SQLAlchemyError, ValueError, KeyError, TypeError, AttributeError):
            raise RoleCatalogUnavailableError("Current role catalog is unavailable") from None

    def active():
        try:
            with factory() as db:
                rows = tuple(db.scalars(select(RoleRow).order_by(RoleRow.role_id)))
                if {r.role_id for r in rows} != {r.value for r in RoleId}:
                    raise RoleCatalogUnavailableError("Current role catalog is incomplete")
                return tuple(_profile(r) for r in rows if r.status == "active")
        except (SQLAlchemyError, ValueError, KeyError, TypeError, AttributeError):
            raise RoleCatalogUnavailableError("Current role catalog is unavailable") from None

    return RoleRegistry(resolve, active)


def import_roles(factory, records=None):
    """Explicit operator import; never runs on HTTP requests or app startup."""
    if records is None:
        records = json.loads(Path(__file__).with_name("role_seed.json").read_text())
    if len(records) != 21 or {r["role_id"] for r in records} != {r.value for r in RoleId}:
        raise ValueError("Import requires exactly 21 canonical roles")
    for r in records:
        validate_definition(dict(r, revision=1))
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    with factory.begin() as db:
        for record in sorted(records, key=lambda r: r["role_id"]):
            row = db.scalar(
                select(RoleRow).where(RoleRow.role_id == record["role_id"]).with_for_update()
            )
            now = datetime.now(UTC)
            if row is None:
                db.add(RoleRow(**record, revision=1, created_at=now, updated_at=now))
                counts["inserted"] += 1
            elif all(getattr(row, k) == v for k, v in record.items()):
                counts["unchanged"] += 1
            else:
                for k, v in record.items():
                    setattr(row, k, v)
                row.revision += 1
                row.updated_at = now
                counts["updated"] += 1
    return counts


def main():
    """Explicit import into configured database; never log connection strings or source payloads."""
    import os

    from .database import create_database_engine, create_session_factory

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required for explicit Roles import")
    engine = create_database_engine(url)
    try:
        try:
            print(json.dumps(import_roles(create_session_factory(engine)), sort_keys=True))
        except (SQLAlchemyError, ValueError, KeyError, TypeError, AttributeError):
            raise SystemExit("Roles import failed; no changes committed") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
