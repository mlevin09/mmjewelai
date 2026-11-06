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


def _request(ctx, state, choice="NO"):
    from uuid import uuid4

    from test_prompt_enrichment_http import _message

    message = _message(ctx.client, str(ctx.sid), str(ctx.org), choice)
    return dict(
        schema_version="1.0.0",
        request_id=str(uuid4()),
        message_id=message["message_id"],
        expected_frame=state["state"]["current_frame"],
        anything_else=choice,
    )


def _post(ctx, body, **kwargs):
    return ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions",
        headers=kwargs.pop("headers", ctx.headers),
        json=body,
        **kwargs,
    )


def _rows(ctx):
    from jewelai_persistence.models import PromptCompletionRow
    from sqlalchemy import select

    with ctx.repo._session_factory() as db:
        return list(
            db.scalars(select(PromptCompletionRow).order_by(PromptCompletionRow.sequence_number))
        )


def test_completion_identical_concurrent_postgres(engine, tmp_path, enabled):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from test_conversation import read
    from test_f04_http import f04_session, restart
    from test_f05_history import initial
    from test_prompt_completion import current

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        body = _request(ctx, read(ctx))
        start = Barrier(2)

        def submit():
            start.wait(timeout=10)
            return _post(ctx, body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            results = [f.result(timeout=30) for f in futures]
        assert [r.status_code for r in results] == [200, 200], [r.json() for r in results]
        assert sorted(r.json()["replayed"] for r in results) == [False, True]
        assert results[0].json()["final_prompt"] == results[1].json()["final_prompt"]
        assert len(_rows(ctx)) == 1
        with restart(ctx, engine):
            assert current(ctx).json()["final_prompt"] == results[0].json()["final_prompt"]


def test_completion_distinct_concurrent_postgres(engine, tmp_path, enabled):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from test_conversation import read
    from test_f04_http import f04_session
    from test_f05_history import initial
    from test_prompt_completion import current

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        state = read(ctx)
        bodies = [_request(ctx, state, choice) for choice in ("YES", "NO")]
        start = Barrier(2)

        def submit(body):
            start.wait(timeout=10)
            return _post(ctx, body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, b) for b in bodies]
            results = [f.result(timeout=30) for f in futures]
        assert [r.status_code for r in results] == [200, 200], [r.json() for r in results]
        rows = _rows(ctx)
        assert [r.sequence_number for r in rows] == [1, 2]
        latest = current(ctx)
        assert latest.status_code == 200, latest.json()
        assert latest.json()["completion_id"] == str(rows[-1].completion_id)
        assert latest.json()["status"] == (
            "FINAL" if rows[-1].payload["request"]["anything_else"] == "NO" else "EDITING"
        )
        for body in bodies:
            replay = _post(ctx, body)
            assert replay.status_code == 200 and replay.json()["replayed"]
            assert replay.json()["is_current"] == (
                replay.json()["completion_id"] == str(rows[-1].completion_id)
            )


@pytest.mark.parametrize("winner", ["completion", "edit"])
def test_completion_edit_lock_race_postgres(engine, tmp_path, enabled, winner, record_property):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import ContextVar
    from threading import Event
    from time import monotonic, sleep

    from sqlalchemy import event, text
    from test_conversation import read
    from test_f04_http import f04_session
    from test_f05_history import initial
    from test_prompt_completion import current
    from test_prompt_enrichment_http import _message

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        state = read(ctx)
        body = _request(ctx, state)
        message = _message(ctx.client, str(ctx.sid), str(ctx.org), "Use platinum.")
        frame = state["state"]["current_frame"]
        edit_body = dict(
            schema_version="2.0.0",
            message_id=message["message_id"],
            expected_revision_id=frame["revision_id"],
            expected_enrichment_cycle_id=frame["enrichment_cycle_id"],
            expected_enrichment_result_hash=frame["enrichment_result_hash"],
            expected_clarification_plan_hash=frame["plan_hash"],
        )
        locked, contender, release = Event(), Event(), Event()
        role_context = ContextVar("completion_race_role", default=None)
        observed = {}

        def session_lock(statement):
            return "design_session" in statement.lower() and "FOR UPDATE" in statement.upper()

        def before(conn, cursor, statement, parameters, context, executemany):
            sql = statement.upper()
            # Correction first performs a scoped FOR SHARE history read. It can
            # legitimately block before reaching its write transaction's FOR UPDATE.
            lock_mode = next(
                (
                    m
                    for m in ("FOR NO KEY UPDATE", "FOR KEY SHARE", "FOR UPDATE", "FOR SHARE")
                    if m in sql
                ),
                None,
            )
            if (
                lock_mode
                and "design_session" in statement.lower()
                and role_context.get() == "loser"
            ):
                observed["waiter_pid"] = conn.connection.driver_connection.info.backend_pid
                observed["waiter_lock"] = lock_mode
                contender.set()

        def after(conn, cursor, statement, parameters, context, executemany):
            if session_lock(statement) and role_context.get() == "winner" and not locked.is_set():
                observed["holder_pid"] = conn.connection.driver_connection.info.backend_pid
                locked.set()  # Real PG row lock acquired, not a mocked reservation.
                assert release.wait(20)

        def invoke(which, role):
            role_context.set(role)
            if which == "completion":
                return _post(ctx, body)
            return ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
                headers=ctx.headers,
                json=edit_body,
            )

        event.listen(engine, "before_cursor_execute", before)
        event.listen(engine, "after_cursor_execute", after)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(invoke, winner, "winner")
                try:
                    assert locked.wait(10), "First transaction did not acquire the session row"
                    second = pool.submit(
                        invoke, "edit" if winner == "completion" else "completion", "loser"
                    )
                    assert contender.wait(10), (
                        "Second request did not attempt a scoped session read/write lock"
                    )
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        with engine.connect() as db:
                            blockers = db.scalar(
                                text("SELECT pg_blocking_pids(:pid)"),
                                {"pid": observed["waiter_pid"]},
                            )
                        if observed["holder_pid"] in blockers:
                            break
                        sleep(0.02)
                    else:
                        pytest.fail("PostgreSQL did not confirm the scoped lock wait")
                    record_property("verified_postgres_lock_wait", observed["waiter_lock"])
                    record_property("first_writer", winner)
                finally:
                    release.set()
                results = {winner: first.result(timeout=30)}
                results["edit" if winner == "completion" else "completion"] = second.result(
                    timeout=30
                )
        finally:
            release.set()
            event.remove(engine, "before_cursor_execute", before)
            event.remove(engine, "after_cursor_execute", after)
        assert results["edit"].status_code == 200, results["edit"].json()
        assert read(ctx)["revision"]["design"]["metal"]["material"]["value"] == "platinum"
        if winner == "edit":
            assert results["completion"].status_code == 409, results["completion"].json()
            assert results["completion"].json()["error"] == "stale_completion_frame"
            assert not _rows(ctx)
        else:
            assert results["completion"].status_code == 200, results["completion"].json()
            assert current(ctx).status_code == 409
            replay = _post(ctx, body)
            assert replay.status_code == 200 and not replay.json()["is_current"]
            assert len(_rows(ctx)) == 1


@pytest.mark.parametrize("verb", ["update", "delete"])
def test_completion_append_only_trigger_postgres(engine, tmp_path, enabled, verb):
    from jewelai_persistence.models import PromptCompletionRow
    from sqlalchemy import delete, update
    from sqlalchemy.exc import DBAPIError
    from test_conversation import read
    from test_f04_http import f04_session
    from test_f05_history import initial
    from test_prompt_completion import current

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        completed = _post(ctx, _request(ctx, read(ctx)))
        assert completed.status_code == 200, completed.json()
        original = current(ctx).json()
        statement = (
            update(PromptCompletionRow).values(sequence_number=77)
            if verb == "update"
            else delete(PromptCompletionRow)
        )
        with pytest.raises(DBAPIError, match="Prompt completion is immutable"):
            with engine.begin() as db:
                db.execute(statement)
        assert current(ctx).json() == original
        assert len(_rows(ctx)) == 1


def test_completion_postflush_rollback_postgres(engine, tmp_path, enabled, monkeypatch):
    from test_prompt_completion import (
        test_completion_validation_failure_rolls_back_append as exercise,
    )

    exercise(engine, tmp_path, enabled, monkeypatch)


def test_completion_get_source_tenant_and_idempotency_postgres(engine, tmp_path, enabled):
    from uuid import UUID

    from jewelai_persistence.models import MessageRow
    from sqlalchemy import event
    from test_conversation import read
    from test_f04_http import f04_session, restart
    from test_f05_history import initial
    from test_prompt_completion import current

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        body = _request(ctx, read(ctx))
        completed = _post(ctx, body)
        assert completed.status_code == 200, completed.json()
        assert _post(ctx, body).json()["replayed"]
        assert _post(ctx, {**body, "anything_else": "YES"}).status_code == 409
        assert (
            _post(
                ctx, body, headers={**ctx.headers, "Authorization": "Bearer test-outsider"}
            ).status_code
            == 404
        )
        statements = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            with restart(ctx, engine):
                result = current(ctx)
                assert result.status_code == 200, result.json()
                assert result.json()["final_prompt"] == completed.json()["final_prompt"]
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}
        with ctx.repo._session_factory.begin() as db:
            message = db.get(MessageRow, UUID(body["message_id"]))
            message.content = "YES"  # Existing Message corruption; completion row stays immutable.
        assert current(ctx).status_code == 500
        replay = _post(ctx, body)
        assert replay.status_code == 500 and replay.json()["error"] == "invalid_completion_history"
