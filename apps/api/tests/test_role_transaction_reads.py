"""Role reads borrow the existing unit-of-work Session, including failure paths."""

import json
from contextlib import nullcontext

import pytest
from conftest import ROOT
from jewelai_domain.roles import RoleCatalogUnavailableError
from jewelai_persistence import Base, create_session_factory
from jewelai_persistence.models import RoleRow
from jewelai_persistence.preparations import locked_reader
from jewelai_persistence.roles import import_roles
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool


@pytest.fixture
def memory_roles():
    engine = create_engine(
        "sqlite+pysqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    import_roles(factory)
    with engine.begin() as db:
        db.execute(text("CREATE TABLE disposable_role_read_probe (id INTEGER PRIMARY KEY)"))
    try:
        yield engine, factory
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["resolve", "list", "malformed"])
@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_role_reader_never_owns_outer_transaction(memory_roles, operation, finish):
    engine, factory = memory_roles
    if operation == "malformed":
        with factory.begin() as db:
            db.get(RoleRow, "RR-C25").role_data = {"invalid": True}
    commits, rollbacks = [], []
    event.listen(engine, "commit", lambda connection: commits.append(True))
    event.listen(engine, "rollback", lambda connection: rollbacks.append(True))

    class CallerAbort(Exception):
        pass

    with pytest.raises(CallerAbort) if finish == "rollback" else nullcontext():
        with factory.begin() as db:
            db.execute(text("INSERT INTO disposable_role_read_probe VALUES (1)"))
            reader = locked_reader(db)
            roles = reader.current_role_registry
            assert roles is reader.current_role_registry  # binding only, not cached definitions
            if operation == "resolve":
                assert roles.get_profile("RR-C25").role_id == "RR-C25"
            elif operation == "list":
                assert len(roles) == 21
                assert len(tuple(roles)) == 21
            else:
                with pytest.raises(RoleCatalogUnavailableError):
                    roles.get_profile("RR-C25")
            assert commits == rollbacks == []
            assert db.in_transaction()
            assert db.scalar(text("SELECT count(*) FROM disposable_role_read_probe")) == 1
            db.execute(text("INSERT INTO disposable_role_read_probe VALUES (2)"))
            if finish == "rollback":
                raise CallerAbort()
    assert len(commits) == (finish == "commit")
    assert len(rollbacks) == (finish == "rollback")
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM disposable_role_read_probe")) == (
            2 if finish == "commit" else 0
        )


def test_runtime_role_binding_is_local_and_covers_rules_and_questions(memory_roles):
    from jewelai_domain import RoleRegistry
    from jewelai_domain.models_v1_1 import validate_design_revision

    from jewelai_api.artifacts import bind_runtime_roles, load_runtime_artifacts
    from jewelai_api.settings import ArtifactVersions

    def forbidden(*args):
        pytest.fail("Transaction-bound rules/questions attempted a separate role reader")

    original_roles = RoleRegistry(forbidden, forbidden)
    artifacts = load_runtime_artifacts(ROOT, ArtifactVersions(), roles=original_roles)
    original_rules, original_questions = artifacts.rules, artifacts.questions
    engine, factory = memory_roles
    with factory.begin() as db:
        db.execute(text("INSERT INTO disposable_role_read_probe VALUES (1)"))
        reader = locked_reader(db)
        scoped = bind_runtime_roles(artifacts, reader.current_role_registry)
        assert bind_runtime_roles(scoped, reader.current_role_registry) is scoped
        question = scoped.questions.render("CENTER_STONE_SHAPE", "RR-C25", "en")
        assert question.role_id == "RR-C25"
        revision = validate_design_revision(
            json.loads((ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text())
        )
        scoped.rules.evaluate(revision, role_id="RR-C25")
        assert artifacts.roles is original_roles
        assert artifacts.rules is original_rules and artifacts.questions is original_questions
        assert db.scalar(text("SELECT count(*) FROM disposable_role_read_probe")) == 1


def test_f04_staticpool_http_history_restart_and_preparation(memory_roles, tmp_path):
    from test_f04_http import (
        test_f04_three_cycle_persisted_restoration_and_preparation_http as lifecycle,
    )

    lifecycle(memory_roles[0], tmp_path)
