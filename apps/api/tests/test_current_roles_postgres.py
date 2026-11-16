"""Real Roles migration checks, only after the existing disposable PostgreSQL gate."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import ROOT
from disposable_postgres import verified_ci_postgres
from jewelai_persistence import create_database_engine, create_session_factory
from jewelai_persistence.roles import database_role_registry, import_roles
from sqlalchemy import inspect, text
from test_current_roles import test_role_http_journey_restart_and_cas as _role_journey
from test_generation_preparations_postgres import engine as engine


@pytest.mark.postgres
def test_roles_migration_and_import_postgres(monkeypatch):
    if os.getenv("GITHUB_ACTIONS") != "true":
        pytest.skip(
            "NOT VERIFIED: requires existing independently verified disposable CI PostgreSQL"
        )
    url = verified_ci_postgres()  # Must precede all schema creation or migration.
    schema = "roles_" + uuid4().hex
    control = create_database_engine(url)
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    # Bind search_path on the same verified cluster; no arbitrary external database URL.
    # Keep '=' literal: Alembic's ConfigParser treats percent-encoded '%3D' as
    # interpolation syntax before it can connect to PostgreSQL.
    scoped = url + "?options=-csearch_path=" + schema
    engine = create_database_engine(scoped)
    monkeypatch.setenv("DATABASE_URL", scoped)
    cfg = Config(str(ROOT / "packages/persistence/alembic.ini"))
    try:
        command.upgrade(cfg, "0020_session_retirement")
        before = set(inspect(engine).get_table_names())
        command.upgrade(cfg, "head")
        assert set(inspect(engine).get_table_names()) - before == {"roles"}
        factory = create_session_factory(engine)
        roles = database_role_registry(factory)
        assert len(roles) == 21
        assert sum("passport" in roles[r].role_data for r in roles) == 9
        assert sum(len(roles[r].role_data["personas"]) for r in roles) == 36
        assert import_roles(factory) == {"inserted": 0, "updated": 0, "unchanged": 21}
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            with engine.begin() as db:
                db.execute(text("UPDATE roles SET role_id='retail_client' WHERE role_id='RR-C25'"))
        assert len(database_role_registry(factory)) == 21

        with engine.connect() as db:
            assert (
                db.scalar(
                    text(
                        "SELECT data_type FROM information_schema.columns WHERE table_schema=:s "
                        "AND table_name='roles' AND column_name='role_data'"
                    ),
                    {"s": schema},
                )
                == "jsonb"
            )
            assert (
                db.scalar(
                    text(
                        "SELECT data_type FROM information_schema.columns WHERE table_schema=:s "
                        "AND table_name='roles' AND column_name='merged_from_ids'"
                    ),
                    {"s": schema},
                )
                == "ARRAY"
            )
    finally:
        engine.dispose()
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def test_roles_scoped_url_roundtrips_alembic_config():
    from sqlalchemy.engine import make_url

    url = "postgresql+psycopg://localhost/jewelai_test?options=-csearch_path=roles_" + "a" * 32
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", url)
    assert cfg.get_main_option("sqlalchemy.url") == url
    assert make_url(url).query["options"] == "-csearch_path=roles_" + "a" * 32


@pytest.mark.parametrize("retained", ("referenced_session", "modified_role"))
def test_roles_downgrade_refuses_before_destructive_operations(monkeypatch, retained):
    migration = (
        ScriptDirectory.from_config(Config(str(ROOT / "packages/persistence/alembic.ini")))
        .get_revision("0021_roles_foundation")
        .module
    )

    class RetainedData:
        def scalar(self, statement):
            return (
                1
                if ("JOIN roles" in str(statement)) == (retained == "referenced_session")
                else None
            )

    class NoDestructiveOperations:
        def get_bind(self):
            return RetainedData()

        def __getattr__(self, name):
            pytest.fail("Roles retention guard attempted a destructive operation: " + name)

    monkeypatch.setattr(migration, "op", NoDestructiveOperations())
    with pytest.raises(RuntimeError, match="Current Roles data requires reviewed retention"):
        migration.downgrade()


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("role", "locale", "content"),
    [
        ("RR-C25", "en", "I want a ring with an emerald."),
        ("RR-C10", "ru", "Хочу кольцо с изумрудом."),
    ],
)
def test_current_role_http_journey_postgres(
    client, app, engine, text_understanding_provider, role, locale, content
):
    _role_journey(client, app, engine, text_understanding_provider, role, locale, content)
