"""Single completion lifecycle on independently verified disposable PostgreSQL."""

import os

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from disposable_postgres import verified_ci_postgres
from jewelai_persistence import create_database_engine
from test_prompt_completion import enabled as enabled
from test_prompt_completion import (
    test_complete_unknown_refine_restart_replay_and_latest as _exercise,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def engine(monkeypatch):
    if not os.getenv("TEST_POSTGRES_URL"):
        pytest.skip("TEST_POSTGRES_URL not configured; PostgreSQL proof NOT VERIFIED")
    url = (
        verified_ci_postgres()
    )  # Mandatory cluster/container/job/target/freshness proof BEFORE DDL.
    from uuid import uuid4

    from sqlalchemy import text

    control = create_database_engine(url)
    schema = "completion_" + uuid4().hex
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = url + "?options=-csearch_path=" + schema
    value = create_database_engine(scoped_url)
    monkeypatch.setenv("DATABASE_URL", scoped_url)
    config = Config(str(ROOT / "packages/persistence/alembic.ini"))
    try:
        command.upgrade(config, "head")
        command.check(config)
        yield value
    finally:
        value.dispose()
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def test_completion_lifecycle_postgres(engine, tmp_path, enabled, record_property):
    _exercise(engine, tmp_path, enabled, record_property)
