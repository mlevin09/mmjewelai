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


def test_migration_uses_package_seed_without_checkout_src(tmp_path, monkeypatch):
    import importlib.util
    import shutil
    from pathlib import Path

    directory = tmp_path / "app/packages/persistence"
    shutil.copytree(ROOT / "packages/persistence/migrations", directory / "migrations")
    shutil.copyfile(ROOT / "packages/persistence/alembic.ini", directory / "alembic.ini")
    assert not (directory / "src").exists()
    cfg = Config(str(directory / "alembic.ini"))
    from jewelai_domain.roles import RoleId

    path = Path(cfg.get_main_option("script_location")) / "versions/0021_roles_foundation.py"
    spec = importlib.util.spec_from_file_location("packaged_roles_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    inserted = []

    class RecordingOperations:
        def create_table(self, *args, **kwargs):
            pass

        create_index = create_foreign_key = create_check_constraint = create_table

        def get_bind(self):
            return self

        def execute(self, statement, records):
            inserted.extend(records)

    monkeypatch.setattr(migration, "op", RecordingOperations())
    migration.upgrade()
    assert {row["role_id"] for row in inserted} == {role.value for role in RoleId}
    assert len(inserted) == 21
    assert sum("passport" in row["role_data"] for row in inserted) == 9


@pytest.mark.postgres
@pytest.mark.parametrize("fault", ("none", "missing_seed", "failed_insert"))
def test_packaged_roles_upgrade_retention_and_atomic_retry(tmp_path, monkeypatch, fault):
    import shutil
    from importlib import resources

    from conftest import NOW, create_hierarchy
    from sqlalchemy import MetaData, Table, event
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import IntegrityError
    from test_prompt_enrichment_http import _client

    from jewelai_api.role_selection import STUDIO_ROLE_IDS

    if os.getenv("GITHUB_ACTIONS") != "true":
        pytest.skip("NOT VERIFIED locally: requires existing disposable CI PostgreSQL gate")
    url = verified_ci_postgres()  # Must precede every DDL, including the isolated schema.
    schema = "roles_package_" + uuid4().hex
    control = create_database_engine(url)
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = url + "?options=-csearch_path=" + schema  # Preserve literal '=' for ConfigParser.
    isolated = create_database_engine(scoped)
    monkeypatch.setenv("DATABASE_URL", scoped)
    directory = tmp_path / "app/packages/persistence"
    shutil.copytree(ROOT / "packages/persistence/migrations", directory / "migrations")
    shutil.copyfile(ROOT / "packages/persistence/alembic.ini", directory / "alembic.ini")
    assert not (directory / "src").exists()
    cfg = Config(str(directory / "alembic.ini"))

    def retained(sid):
        with isolated.connect() as db:
            return db.scalar(
                text("SELECT to_jsonb(s) FROM design_session s WHERE session_id=:id"), {"id": sid}
            )

    try:
        command.upgrade(cfg, "0020_session_retirement")
        metadata = MetaData()
        organization = Table("organization", metadata, autoload_with=isolated)
        project = Table("project", metadata, autoload_with=isolated)
        session = Table("design_session", metadata, autoload_with=isolated)
        org, project_id, sid = uuid4(), uuid4(), uuid4()
        with isolated.begin() as db:
            db.execute(
                organization.insert(), dict(organization_id=org, name="Synthetic", created_at=NOW)
            )
            db.execute(
                project.insert(),
                dict(project_id=project_id, organization_id=org, name="Synthetic", created_at=NOW),
            )
            db.execute(
                session.insert(),
                dict(
                    session_id=sid,
                    project_id=project_id,
                    role_id="retail_client",
                    locale="en",
                    created_at=NOW,
                    updated_at=NOW,
                    current_revision_id=uuid4(),
                    design_schema_version="1.0.0",
                    role_artifact_version="1.0.0",
                    dictionary_artifact_version="1.0.0",
                    question_artifact_version="1.0.0",
                    rules_artifact_version="1.0.0",
                    prompt_artifact_version="1.0.0",
                ),
            )
        before = retained(sid)
        if fault != "none":
            with monkeypatch.context() as patch:
                if fault == "missing_seed":
                    native = resources.files
                    patch.setattr(
                        resources,
                        "files",
                        lambda anchor: (
                            tmp_path / "missing"
                            if anchor == "jewelai_persistence"
                            else native(anchor)
                        ),
                    )
                    expected_error = FileNotFoundError
                else:

                    def reject_insert(
                        connection, cursor, statement, parameters, context, executemany
                    ):
                        if statement.lstrip().startswith("INSERT INTO roles"):
                            raise RuntimeError("synthetic catalog insert failure")

                    event.listen(Engine, "before_cursor_execute", reject_insert)
                    expected_error = RuntimeError
                try:
                    with pytest.raises(expected_error):
                        command.upgrade(cfg, "head")
                finally:
                    if fault == "failed_insert":
                        event.remove(Engine, "before_cursor_execute", reject_insert)
            assert not inspect(isolated).has_table("roles")
            with isolated.connect() as db:
                assert db.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0020_session_retirement"
                )
                assert (
                    db.scalar(
                        text(
                            "SELECT count(*) FROM pg_constraint "
                            "WHERE conname='fk_design_session_current_role' "
                            "AND conrelid='design_session'::regclass"
                        )
                    )
                    == 0
                )
            assert retained(sid) == before
        command.upgrade(cfg, "head")
        registry = database_role_registry(create_session_factory(isolated))
        assert len(registry) == 21
        assert all(registry[role].status == "active" for role in STUDIO_ROLE_IDS)
        assert retained(sid) == before
        if fault != "none":
            return  # Recovery proven; exercise HTTP choices once, in the positive case.
        with isolated.connect() as db:
            original_roles = db.scalars(
                text("SELECT to_jsonb(r) FROM roles r ORDER BY role_id")
            ).all()
            assert (
                db.scalar(
                    text(
                        "SELECT convalidated FROM pg_constraint "
                        "WHERE conname='fk_design_session_current_role' "
                        "AND conrelid='design_session'::regclass"
                    )
                )
                is False
            )
        command.upgrade(cfg, "head")
        with isolated.connect() as db:
            assert (
                db.scalars(text("SELECT to_jsonb(r) FROM roles r ORDER BY role_id")).all()
                == original_roles
            )
        with _client(isolated)[0] as client:
            assert len(client.get("/roles").json()) == 21
            assert len(client.get("/ui/catalog").json()["roles"]) == 9
            for role in STUDIO_ROLE_IDS:
                _, _, response = create_hierarchy(client, role_id=role)
                assert response.status_code == 201, response.text
                assert response.json()["role_id"] == role
        with pytest.raises(IntegrityError) as rejected:
            with isolated.begin() as db:
                db.execute(
                    text("UPDATE design_session SET role_id='retail_client' WHERE role_id='RR-C25'")
                )
        assert rejected.value.orig.sqlstate == "23503"
        with pytest.raises(IntegrityError):
            with isolated.begin() as db:
                db.execute(text("DELETE FROM roles WHERE role_id='RR-C25'"))
        assert retained(sid) == before
        assert len(database_role_registry(create_session_factory(isolated))) == 21
    finally:
        isolated.dispose()
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()
