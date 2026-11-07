"""Portable additive migration/retention checks on a newly created temporary DB."""

import importlib.util
from functools import partial

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from conftest import ROOT, create_hierarchy
from jewelai_persistence.models import Base
from sqlalchemy import create_engine, inspect, text
from test_generation_preparations_postgres import seed_checkpoint_session
from test_prompt_enrichment_http import _client


def test_isolated_retirement_upgrade_preserves_checkpoint_source_and_tombstone(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(ROOT / "packages/persistence/alembic.ini"))
    command.upgrade(cfg, "0015_reference_verification")
    engine = create_engine(url)
    client, _ = _client(engine)
    with client:
        repo = client.app.state.service.repository
        with monkeypatch.context() as checkpoint:
            checkpoint.setattr(
                repo, "create_design_session", partial(seed_checkpoint_session, repo, engine)
            )
            oid, _, created = create_hierarchy(client)
        assert created.status_code == 201, created.json()
        sid = created.json()["session_id"]
        with engine.connect() as db:
            before = db.execute(text("SELECT snapshot FROM specification_revision")).scalar_one()
        spec = importlib.util.spec_from_file_location(
            "retirement",
            ROOT / "packages/persistence/migrations/versions/0020_session_retirement.py",
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        # Existing migration0016 is PostgreSQL-only. Test the new additive unit
        # itself here; full head upgrade/check remains the gated PostgreSQL proof.
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                migration.upgrade()
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                migration.downgrade()
                migration.upgrade()
        assert {"deleted_at", "deleted_by_principal_id"} <= {
            c["name"] for c in inspect(engine).get_columns("design_session")
        }
        assert (
            client.get(f"/sessions/{sid}", headers={"X-Organization-ID": oid}).json()
            == created.json()
        )
        assert (
            client.delete(f"/sessions/{sid}", headers={"X-Organization-ID": oid}).status_code == 204
        )
        with engine.connect() as db:
            assert (
                db.execute(text("SELECT snapshot FROM specification_revision")).scalar_one()
                == before
            )
        with pytest.raises(RuntimeError, match="tombstones"):
            with engine.begin() as db:
                with Operations.context(MigrationContext.configure(db)):
                    migration.downgrade()
        with engine.connect() as db:
            assert (
                db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0015_reference_verification"
            )
            assert db.scalar(text("SELECT deleted_at FROM design_session")) is not None
    engine.dispose()


def test_isolated_historical_check_upgrade_downgrade_does_not_change_current_schema(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path / 'check.db'}"
    spec = importlib.util.spec_from_file_location(
        "f04_check", ROOT / "packages/persistence/migrations/versions/0018_f04_preparation_v2.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    columns = [
        (c["name"], str(c["type"]), c["nullable"])
        for c in inspect(engine).get_columns("design_session")
    ]
    with engine.begin() as db:
        with Operations.context(MigrationContext.configure(db)):
            migration.downgrade()
        checks = inspect(db).get_check_constraints("generation_preparation")
        assert any(
            c["name"] == "ck_preparation_version" and "2.0.0" not in c["sqltext"] for c in checks
        )
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert [
            (c["name"], str(c["type"]), c["nullable"])
            for c in inspect(db).get_columns("design_session")
        ] == columns
    engine.dispose()
