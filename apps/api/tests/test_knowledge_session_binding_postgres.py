"""KRT PostgreSQL proofs inherit the existing independently verified disposable-schema gate."""

import pytest
from jewelai_persistence.models import KnowledgeReleaseBindingRow
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from test_generation_preparations_postgres import engine as engine
from test_knowledge_session_binding import (
    test_duplicate_and_concurrent_initial_are_single_binding as concurrent_start,
)
from test_knowledge_session_binding import (
    test_failed_initial_operation_has_no_binding_pin_cycle_or_revision as atomic_failure,
)
from test_knowledge_session_binding import (
    test_new_session_rejects_legacy_but_historical_pin_restores_without_rewriting as legacy,
)
from test_persistence import build_service, create_persisted_session
from test_prompt_enrichment_runtime import _request, _runtime


def test_postgres_concurrent_initial_binding(engine, tmp_path):
    concurrent_start(engine, tmp_path)


@pytest.mark.parametrize("failure", ["plan_write", "stale", "report"])
def test_postgres_atomic_initial_binding(engine, tmp_path, monkeypatch, failure):
    atomic_failure(engine, tmp_path, monkeypatch, failure)


def test_postgres_legacy_restore(engine, tmp_path):
    legacy(engine, tmp_path)


def test_postgres_binding_is_append_only(engine, tmp_path):
    service = build_service(engine)
    org, _, session = create_persisted_session(service)
    runtime, *_ = _runtime(service, tmp_path)
    runtime.start_initial_message(_request(service, org, session, "Create an oval ring."))
    with engine.connect() as db:
        before = db.scalar(select(KnowledgeReleaseBindingRow.payload))
    for statement in (
        update(KnowledgeReleaseBindingRow).values(content_hash="0" * 64),
        KnowledgeReleaseBindingRow.__table__.delete(),
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            with engine.begin() as db:
                db.execute(statement)
    with engine.connect() as db:
        assert db.scalar(select(KnowledgeReleaseBindingRow.payload)) == before
