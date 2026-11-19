"""US-01 qualification behind the unchanged disposable PostgreSQL gate."""

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from conftest import ROOT
from jewelai_persistence.models import InitialConversationTurnRow
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from test_generation_preparations_postgres import engine as engine
from test_natural_turn import EN, RU, Model, get, post, prepare, real_client
from test_natural_turn import (
    test_rejected_precommit_read_is_atomic_and_delivery_failure_is_honest as _rollback,
)
from test_professional_knowledge_http import real_config as real_config

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("locale,text", [("ru", RU), ("en", EN)])
def test_us01_actual_migration_network_outside_locks_and_write_once(
    engine, real_config, locale, text
):
    from jewelai_persistence.models import DesignSessionRow

    model = Model()
    with real_client(engine, real_config, conversation_model=model) as (client, app, _):
        sid, oid, parent, request = prepare(client, app, locale, text)
        original = model.interpret

        def unlocked():
            # A separate physical PG connection can lock the same row while
            # either remote phase executes. NOWAIT must not be weakened.
            with engine.begin() as db:
                assert (
                    db.scalar(
                        select(DesignSessionRow.session_id)
                        .where(DesignSessionRow.session_id == sid)
                        .with_for_update(nowait=True)
                    )
                    == sid
                )

        def interpret(context):
            unlocked()
            return original(context)

        model.interpret = interpret
        model.before_reply = lambda _: unlocked()
        result = post(client, sid, oid, request)
        assert result.status_code == 201, result.json()
        body = result.json()
        assert body["delivered_reply"]["origin"] == "model"
        assert body["current_revision"]["revision_id"] != str(parent.revision_id)
        assert post(client, sid, oid, request).json() == body
        assert len(model.calls) == 2
        for mutation in (
            update(InitialConversationTurnRow)
            .where(InitialConversationTurnRow.session_id == sid)
            .values(input_hash="0" * 64),
            update(InitialConversationTurnRow)
            .where(InitialConversationTurnRow.session_id == sid)
            .values(reply_payload=None, reply_hash=None),
            delete(InitialConversationTurnRow).where(InitialConversationTurnRow.session_id == sid),
        ):
            with pytest.raises(DBAPIError):
                with engine.begin() as db:
                    db.execute(mutation)
        migration = (
            ScriptDirectory.from_config(Config(str(ROOT / "packages/persistence/alembic.ini")))
            .get_revision("0023_initial_conversation_turn")
            .module
        )
        with engine.begin() as db:
            with Operations.context(MigrationContext.configure(db)):
                with pytest.raises(RuntimeError, match="retention"):
                    migration.downgrade()
        assert get(client, sid, oid).json() == body
    with real_client(engine, real_config, conversation_model=None) as (client, _, _):
        assert get(client, sid, oid).json() == body


def test_us01_precommit_failure_rolls_back_and_lost_delivery_retains_commit_postgres(
    engine, real_config, monkeypatch
):
    _rollback(engine, real_config, monkeypatch)
