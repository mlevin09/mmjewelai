"""Live disposable PostgreSQL only through the unchanged independent safety gate."""

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from conftest import ROOT
from jewelai_persistence import create_session_factory
from jewelai_persistence.models import FirstConversationTurnRow
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from test_first_turn import EN, RU, get, post, setup
from test_first_turn import (
    test_final_validation_failure_rolls_back_revision_cycle_pin_and_reply as _rollback,
)
from test_generation_preparations_postgres import engine as engine
from test_professional_knowledge_http import real_client
from test_professional_knowledge_http import real_config as real_config

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("locale,sentence", [("ru", RU), ("en", EN)])
def test_first_turn_real_postgres_migration_http_immutability_and_downgrade(
    engine, real_config, locale, sentence
):
    with real_client(engine, real_config) as (client, app, _):
        sid, oid, body = setup(client, app, sentence, locale)
        result = post(client, sid, oid, body)
        assert result.status_code == 201, result.json()
        # PostgreSQL migration, not just SQLAlchemy create_all, installed these triggers.
        for operation in (
            update(FirstConversationTurnRow)
            .where(FirstConversationTurnRow.session_id == sid)
            .values(content_hash="0" * 64),
            delete(FirstConversationTurnRow).where(FirstConversationTurnRow.session_id == sid),
        ):
            with pytest.raises(DBAPIError):
                with engine.begin() as db:
                    db.execute(operation)
        with pytest.raises(DBAPIError):
            with engine.begin() as db:
                db.execute(
                    text("UPDATE enrichment_cycle SET source_contract=NULL WHERE session_id=:sid"),
                    {"sid": sid},
                )
        cfg = Config(str(ROOT / "packages/persistence/alembic.ini"))
        migration = (
            ScriptDirectory.from_config(cfg).get_revision("0022_first_conversation_turn").module
        )
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                with pytest.raises(RuntimeError, match="retention"):
                    migration.downgrade()
        assert get(client, sid, oid).json() == result.json()
        with create_session_factory(engine)() as db:
            assert db.scalar(select(FirstConversationTurnRow.session_id)) == sid


def test_first_turn_actual_postgres_precommit_failure_is_atomic(engine, real_config, monkeypatch):
    _rollback(engine, real_config, monkeypatch)
