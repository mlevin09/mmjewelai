"""Real PostgreSQL schedules for B2-R1/R2; only independently verified owned schemas."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from test_effective_readiness import _answer, _correct
from test_effective_readiness import ready_session as ready_session
from test_generation_preparations import counts, expected, post
from test_generation_preparations_postgres import engine as engine


def _wait_until(predicate):
    """Wait on actual database lock state/transaction outcome, not a guessed sleep schedule."""
    deadline = monotonic() + 15
    tick = Event()
    while monotonic() < deadline:
        if predicate():
            return
        tick.wait(0.02)
    pytest.fail("Expected PostgreSQL synchronization boundary was not reached")


def _blocked(engine, pid):
    with engine.connect() as db:
        return bool(db.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}))


def _version(engine):
    with engine.connect() as db:
        return db.scalar(text("SELECT version_num FROM alembic_version"))


def _downgrade():
    command.downgrade(
        Config(str(ROOT / "packages/persistence/alembic.ini")), "0015_reference_verification"
    )


def test_writer_first_downgrade_waits_then_refuses_without_losing_history(
    ready_session, engine, capfd
):
    ctx = ready_session()
    request = expected(ctx)
    writer_held, release_writer, downgrade_started = Event(), Event(), Event()
    downgrade_pid = []

    def before(conn, cursor, statement, parameters, context, many):
        sql = " ".join(statement.split()).upper()
        if "INSERT INTO GENERATION_COMMAND" in sql:
            writer_held.set()  # preparation INSERT already flushed, transaction not committed
            assert release_writer.wait(20)

    def migration_before(conn, cursor, statement, parameters, context, many):
        if conn.engine.url != engine.url:
            return
        sql = " ".join(statement.split()).upper()
        if ("LOCK TABLE" in sql or "SELECT COUNT(*)" in sql) and "GENERATION_" in sql:
            downgrade_pid[:] = [conn.connection.driver_connection.info.backend_pid]
            downgrade_started.set()

    event.listen(engine, "before_cursor_execute", before)
    event.listen(Engine, "before_cursor_execute", migration_before)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(post, ctx, request)
            assert writer_held.wait(10)
            downgrade = pool.submit(_downgrade)
            try:
                assert downgrade_started.wait(10)
                _wait_until(lambda: downgrade.done() or _blocked(engine, downgrade_pid[0]))
            finally:
                release_writer.set()
            assert writer.result(timeout=25).status_code == 201
            with pytest.raises(RuntimeError, match="Populated preparation history"):
                downgrade.result(timeout=25)
    finally:
        release_writer.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(Engine, "before_cursor_execute", migration_before)
    assert counts(engine) == (1, 1, 0, 0)
    assert _version(engine) == "0016_generation_preparations"
    with capfd.disabled():
        print(
            "B2_R1_WRITER_FIRST: committed 201; downgrade refused; both rows intact; version 0016"
        )


def test_downgrade_first_excludes_writer_before_empty_check_and_drop(ready_session, engine, capfd):
    ctx = ready_session()
    request = expected(ctx)
    checked, release_drop, writer_started = Event(), Event(), Event()
    writer_pid = []

    def migration_before(conn, cursor, statement, parameters, context, many):
        if conn.engine.url == engine.url and statement.strip().upper().startswith(
            "DROP TABLE GENERATION_COMMAND"
        ):
            # The original vulnerable check/drop boundary. Fixed code holds BOTH exclusive locks.
            checked.set()
            assert release_drop.wait(20)

    def writer_before(conn, cursor, statement, parameters, context, many):
        if checked.is_set() and "FROM generation_command" in statement:
            writer_pid[:] = [conn.connection.driver_connection.info.backend_pid]
            writer_started.set()

    event.listen(Engine, "before_cursor_execute", migration_before)
    event.listen(engine, "before_cursor_execute", writer_before)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            downgrade = pool.submit(_downgrade)
            assert checked.wait(10)
            writer = pool.submit(post, ctx, request)
            try:
                assert writer_started.wait(10)
                _wait_until(lambda: writer.done() or _blocked(engine, writer_pid[0]))
                committed_before_drop = writer.done() and writer.result().status_code == 201
            finally:
                release_drop.set()
            downgrade.result(timeout=25)
            response = writer.result(timeout=25)
    finally:
        release_drop.set()
        event.remove(Engine, "before_cursor_execute", migration_before)
        event.remove(engine, "before_cursor_execute", writer_before)
    assert not committed_before_drop, "Downgrade deleted successfully committed immutable history"
    assert response.status_code == 503  # writer rolls back when locked tables cease to exist
    assert _version(engine) == "0015_reference_verification"
    with engine.connect() as db:
        assert db.scalar(text("SELECT to_regclass('generation_preparation')")) is None
        assert db.scalar(text("SELECT to_regclass('generation_command')")) is None
    command.upgrade(Config(str(ROOT / "packages/persistence/alembic.ini")), "head")
    command.check(Config(str(ROOT / "packages/persistence/alembic.ini")))
    assert counts(engine) == (0, 0, 0, 0)
    with capfd.disabled():
        print(
            "B2_R1_DOWNGRADE_FIRST: writer excluded/503 rollback; "
            "empty downgrade 0015; reupgrade 0016"
        )


@pytest.mark.parametrize("operation", ["correction", "answer", "skip"])
@pytest.mark.parametrize("reader", ["create", "get"])
def test_session_first_writer_and_org_first_preparation_do_not_deadlock(
    ready_session, engine, capfd, operation, reader
):
    ctx = ready_session()
    original_request, key = expected(ctx), uuid4()
    original = post(ctx, original_request, key)
    assert original.status_code == 201
    if operation in ("answer", "skip"):
        _correct(ctx, "I prefer yellow.")
    request = expected(ctx)
    path = f"/sessions/{ctx.sid}/generation-preparations/{original.json()['preparation_id']}"
    session_locked, org_locked, release_writer = Event(), Event(), Event()
    reader_pid, deadlocks = [], []

    def after(conn, cursor, statement, parameters, context, many):
        sql = " ".join(statement.split()).upper()
        if "FROM DESIGN_SESSION JOIN PROJECT" in sql and "FOR UPDATE" in sql:
            if not session_locked.is_set():
                session_locked.set()
                assert release_writer.wait(20)
        if "FROM ORGANIZATION WHERE" in sql and "FOR " in sql:
            reader_pid[:] = [conn.connection.driver_connection.info.backend_pid]
            org_locked.set()

    def error(context):
        if getattr(context.original_exception, "sqlstate", None) == "40P01":
            deadlocks.append("40P01")

    event.listen(engine, "after_cursor_execute", after)
    event.listen(engine, "handle_error", error)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = (
                pool.submit(_correct, ctx, "Do not add a halo.")
                if operation == "correction"
                else pool.submit(
                    _answer,
                    ctx,
                    "metal.color",
                    decision="SKIP" if operation == "skip" else "ACCEPT",
                )
            )
            assert session_locked.wait(10)
            retained = (
                pool.submit(post, ctx, request)
                if reader == "create"
                else pool.submit(ctx.client.get, path, headers=ctx.headers)
            )
            try:
                assert org_locked.wait(10)
                _wait_until(lambda: _blocked(engine, reader_pid[0]))
            finally:
                release_writer.set()
            writer.result(timeout=25)
            response = retained.result(timeout=25)
    finally:
        release_writer.set()
        event.remove(engine, "after_cursor_execute", after)
        event.remove(engine, "handle_error", error)
    assert deadlocks == []
    if reader == "create":
        assert response.status_code == 409
        assert response.json()["error"] in (
            "stale_revision",
            "enrichment_cycle_mismatch",
            "stale_clarification_plan",
        )
    else:
        assert response.status_code == 200 and response.json() == original.json()
    assert counts(engine) == (1, 1, 0, 0)  # old preparation only; writer commits as one unit
    assert post(ctx, original_request, key).json() == original.json()
    with capfd.disabled():
        print(
            f"B2_R2_OVERLAP: {operation}/{reader}; no 40P01; "
            f"status {response.status_code}; atomic history"
        )


def test_revocation_holding_org_lock_prevents_later_preparation(ready_session, engine, capfd):
    ctx = ready_session()
    member = ctx.client.get("/me", headers={"Authorization": "Bearer test-lock-member"}).json()
    membership = f"/organizations/{ctx.org}/memberships"
    assert (
        ctx.client.post(
            membership, json={"principal_id": member["principal_id"], "role": "member"}
        ).status_code
        == 201
    )
    request = expected(ctx)
    deleted, release_revoke, preparing = Event(), Event(), Event()
    pid = []

    def after(conn, cursor, statement, parameters, context, many):
        if statement.startswith("DELETE FROM organization_membership"):
            deleted.set()
            assert release_revoke.wait(20)

    def before(conn, cursor, statement, parameters, context, many):
        sql = " ".join(statement.split()).upper()
        if deleted.is_set() and "FROM ORGANIZATION WHERE" in sql and "FOR " in sql:
            pid[:] = [conn.connection.driver_connection.info.backend_pid]
            preparing.set()

    event.listen(engine, "after_cursor_execute", after)
    event.listen(engine, "before_cursor_execute", before)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoke = pool.submit(ctx.client.delete, f"{membership}/{member['principal_id']}")
            assert deleted.wait(10)
            prepare = pool.submit(
                ctx.client.post,
                f"/sessions/{ctx.sid}/generation-preparations",
                headers={
                    **ctx.headers,
                    "Authorization": "Bearer test-lock-member",
                    "Idempotency-Key": str(uuid4()),
                },
                json=request,
            )
            try:
                assert preparing.wait(10)
                _wait_until(lambda: _blocked(engine, pid[0]))
            finally:
                release_revoke.set()
            assert revoke.result(timeout=25).status_code == 204
            assert prepare.result(timeout=25).status_code == 404
    finally:
        release_revoke.set()
        event.remove(engine, "after_cursor_execute", after)
        event.remove(engine, "before_cursor_execute", before)
    assert counts(engine) == (0, 0, 0, 0)
    with capfd.disabled():
        print("B2_R2_REVOCATION: real org-lock wait; revoked member denied; zero retained rows")
