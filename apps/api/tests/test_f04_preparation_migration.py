"""CHECK-only migration proof in newly created isolated SQLite databases.

This proves version admission and retention, not preparation2 semantic/runtime support.
No environment URL, shared database or preprod resource is used.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[3]


def migration():
    path = ROOT / "packages/persistence/migrations/versions/0018_f04_preparation_v2.py"
    spec = importlib.util.spec_from_file_location("f04_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(db):
    return tuple(
        db.execute(text("SELECT id,schema_version,payload FROM generation_preparation ORDER BY id"))
    )


def column_snapshot(db):
    return tuple(
        {**c, "type": str(c["type"])} for c in inspect(db).get_columns("generation_preparation")
    )


@pytest.mark.parametrize("nonempty", (False, True))
def test_f04_check_upgrade_preserves_old_bytes_and_other_constraints(tmp_path, nonempty):
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "f04-migration.db"))
    with engine.begin() as db:
        db.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        db.execute(text("INSERT INTO parent VALUES(1)"))
        db.execute(
            text("""CREATE TABLE generation_preparation (
            id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES parent(id),
            schema_version VARCHAR(32) NOT NULL, payload BLOB NOT NULL,
            CONSTRAINT ck_preparation_version CHECK(schema_version='1.0.0'),
            CONSTRAINT keep_payload_size CHECK(length(payload)<=2097152),
            CONSTRAINT keep_parent_unique UNIQUE(parent_id))""")
        )
        if nonempty:
            db.execute(
                text("INSERT INTO generation_preparation VALUES(1,1,'1.0.0',:p)"),
                {"p": b"\x00frozen-original\xff"},
            )
        before = snapshot(db)
        columns = column_snapshot(db)
        fks = inspect(db).get_foreign_keys("generation_preparation")
        uniques = inspect(db).get_unique_constraints("generation_preparation")
        with Operations.context(MigrationContext.configure(db)):
            migration().upgrade()
        assert snapshot(db) == before
        assert column_snapshot(db) == columns
        assert inspect(db).get_foreign_keys("generation_preparation") == fks
        assert inspect(db).get_unique_constraints("generation_preparation") == uniques
        checks = {
            c["name"]: c["sqltext"]
            for c in inspect(db).get_check_constraints("generation_preparation")
        }
        assert "'2.0.0'" in checks["ck_preparation_version"]
        assert "keep_payload_size" in checks
        with Operations.context(MigrationContext.configure(db)):
            migration().downgrade()
        assert snapshot(db) == before
        assert "'2.0.0'" not in next(
            c["sqltext"]
            for c in inspect(db).get_check_constraints("generation_preparation")
            if c["name"] == "ck_preparation_version"
        )
    engine.dispose()


def test_f04_unsafe_downgrade_refuses_before_any_ddl(tmp_path):
    engine = create_engine("sqlite+pysqlite:///" + str(tmp_path / "f04-refusal.db"))
    with engine.begin() as db:
        db.execute(
            text("""CREATE TABLE generation_preparation (
            id INTEGER PRIMARY KEY, schema_version VARCHAR(32), payload BLOB,
            CONSTRAINT ck_preparation_version CHECK(schema_version='1.0.0'))""")
        )
        with Operations.context(MigrationContext.configure(db)):
            migration().upgrade()
        db.execute(
            text("INSERT INTO generation_preparation VALUES(1,'2.0.0',:p)"),
            {"p": b"synthetic-version-admission-only"},
        )
        rows, checks = snapshot(db), inspect(db).get_check_constraints("generation_preparation")
        with Operations.context(MigrationContext.configure(db)):
            with pytest.raises(RuntimeError, match="prevent safe downgrade"):
                migration().downgrade()
        assert snapshot(db) == rows
        assert inspect(db).get_check_constraints("generation_preparation") == checks
        with pytest.raises(IntegrityError):
            db.execute(text("INSERT INTO generation_preparation VALUES(2,'3.0.0',X'00')"))
    engine.dispose()
