"""Real PostgreSQL schedules for B2-R1/R2; only independently verified owned schemas."""

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from conftest import ROOT
from disposable_postgres import _docker, verified_ci_postgres
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from test_effective_readiness import _answer, _correct
from test_effective_readiness import ready_session as ready_session
from test_generation_preparations import counts, expected, post
from test_generation_preparations_postgres import engine as engine
from test_generation_preparations_postgres import retention_snapshot


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


def test_downgrade_refuses_before_using_any_alembic_database_operation(monkeypatch):
    migration = (
        ScriptDirectory.from_config(Config(str(ROOT / "packages/persistence/alembic.ini")))
        .get_revision("0016_generation_preparations")
        .module
    )

    class NoDatabaseOperations:
        def __getattr__(self, name):
            pytest.fail("Unsupported downgrade attempted an Alembic operation: " + name)

    monkeypatch.setattr(migration, "op", NoDatabaseOperations())
    with pytest.raises(RuntimeError, match="separately planned maintenance rollback"):
        migration.downgrade()


@contextmanager
def _observe_postgres(engine, capfd, schedule):
    """Inspect actual driver SQLSTATE and the verified server log window, never raw SQL payloads."""
    verified_ci_postgres()
    containers = []
    for cid in _docker(
        "ps", "--filter", "ancestor=postgres:16", "--format", "{{.ID}}"
    ).splitlines():
        metadata = json.loads(_docker("inspect", cid))[0]
        ports = metadata["NetworkSettings"]["Ports"].get("5432/tcp") or []
        if any(p["HostPort"] == "5432" for p in ports):
            containers.append(cid)
    assert len(containers) == 1
    with engine.connect() as db:
        since = db.scalar(text("SELECT clock_timestamp()")).isoformat()
    states, ddl = [], []

    def error(context):
        if context.engine.url == engine.url:
            states.append(getattr(context.original_exception, "sqlstate", None))

    def before(conn, cursor, statement, parameters, context, many):
        if conn.engine.url == engine.url and statement.lstrip().upper().startswith(
            ("LOCK ", "DROP ", "ALTER ")
        ):
            ddl.append(statement.split()[0].upper())

    event.listen(Engine, "handle_error", error)
    event.listen(Engine, "before_cursor_execute", before)
    try:
        yield
    finally:
        event.remove(Engine, "handle_error", error)
        event.remove(Engine, "before_cursor_execute", before)
        result = subprocess.run(
            ["docker", "logs", "--since", since, containers[0]],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        logs = result.stdout + result.stderr
        deadlocks = logs.lower().count("deadlock detected") + logs.count("40P01")
        with capfd.disabled():
            print(
                "B2_R1A_POSTGRES: "
                + json.dumps(
                    {
                        "schedule": schedule,
                        "sqlstates": states,
                        "deadlock_messages": deadlocks,
                        "downgrade_lock_or_ddl": ddl,
                        "server_log_since": since,
                        "server_log_bytes": len(logs.encode()),
                        "server_log_sha256": hashlib.sha256(logs.encode()).hexdigest(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        assert "40P01" not in states and deadlocks == 0
        assert states == [], "Normal preparation must not suffer a database exception"
        assert ddl == [], "Refused downgrade must not acquire locks or alter schema"


def _assert_preserved(before, after):
    assert before["version"] == after["version"] == "0016_generation_preparations"
    assert before["objects"] == after["objects"]  # includes constraints, triggers and functions
    for table, rows in before["rows"].items():
        assert all(row in after["rows"][table] for row in rows)


@pytest.mark.parametrize("populated", [False, True])
def test_empty_and_populated_downgrade_refuse_without_schema_or_data_change(
    ready_session, engine, capfd, populated
):
    ctx = ready_session()
    if populated:
        assert post(ctx).status_code == 201
    before = retention_snapshot(engine)
    with _observe_postgres(engine, capfd, "populated" if populated else "empty"):
        with pytest.raises(RuntimeError, match="0016 online downgrade is unsupported"):
            _downgrade()
        assert retention_snapshot(engine) == before
    command.check(Config(str(ROOT / "packages/persistence/alembic.ini")))
    command.current(Config(str(ROOT / "packages/persistence/alembic.ini")))


def test_early_command_lookup_writer_survives_unsupported_downgrade(ready_session, engine, capfd):
    ctx = ready_session()
    request = expected(ctx)
    assert post(ctx, request).status_code == 201  # retain original immutable history too
    before_snapshot = retention_snapshot(engine)
    looked_up, release_writer = Event(), Event()
    downgrade_pid = []

    def after(conn, cursor, statement, parameters, context, many):
        if "FROM generation_command" in statement and not looked_up.is_set():
            looked_up.set()  # writer already owns command ACCESS SHARE + parent row locks
            assert release_writer.wait(20)

    def migration_before(conn, cursor, statement, parameters, context, many):
        if conn.engine is not engine and conn.engine.url == engine.url:
            downgrade_pid[:] = [conn.connection.driver_connection.info.backend_pid]

    with _observe_postgres(engine, capfd, "early_command_lookup"):
        event.listen(engine, "after_cursor_execute", after)
        event.listen(Engine, "before_cursor_execute", migration_before)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(post, ctx, request)
                assert looked_up.wait(10)
                downgrade = pool.submit(_downgrade)
                try:
                    _wait_until(
                        lambda: (
                            downgrade.done()
                            or (downgrade_pid and _blocked(engine, downgrade_pid[0]))
                        )
                    )
                finally:
                    release_writer.set()
                assert writer.result(timeout=25).status_code == 201
                with pytest.raises(RuntimeError, match="0016 online downgrade is unsupported"):
                    downgrade.result(timeout=25)
        finally:
            release_writer.set()
            event.remove(engine, "after_cursor_execute", after)
            event.remove(Engine, "before_cursor_execute", migration_before)
    _assert_preserved(before_snapshot, retention_snapshot(engine))
    assert counts(engine) == (2, 2, 0, 0)


def test_fk_parent_writer_survives_downgrade_first_child_access(ready_session, engine, capfd):
    ctx = ready_session()
    request = expected(ctx)
    # Keep retained tables empty: the old downgrade must reach DROP/FK parent locks to
    # reproduce schedule B, rather than stopping at its populated-history check.
    before_snapshot = retention_snapshot(engine)
    parent_locked, release_writer, drop_ready, release_drop = Event(), Event(), Event(), Event()
    writer_lookup, writer_pid = Event(), []

    def writer_after(conn, cursor, statement, parameters, context, many):
        sql = " ".join(statement.split()).upper()
        if "FROM DESIGN_SESSION JOIN PROJECT" in sql and "FOR UPDATE" in sql:
            if not parent_locked.is_set():
                parent_locked.set()
                assert release_writer.wait(20)

    def writer_before(conn, cursor, statement, parameters, context, many):
        if "FROM generation_command" in statement:
            writer_pid[:] = [conn.connection.driver_connection.info.backend_pid]
            writer_lookup.set()

    def migration_before(conn, cursor, statement, parameters, context, many):
        if conn.engine.url == engine.url and statement.strip().upper().startswith(
            "DROP TABLE GENERATION_PREPARATION"
        ):
            drop_ready.set()  # old path held child locks, then needed incompatible FK parent locks
            assert release_drop.wait(20)

    with _observe_postgres(engine, capfd, "fk_parent"):
        event.listen(engine, "after_cursor_execute", writer_after)
        event.listen(engine, "before_cursor_execute", writer_before)
        event.listen(Engine, "before_cursor_execute", migration_before)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(post, ctx, request)
                assert parent_locked.wait(10)
                downgrade = pool.submit(_downgrade)
                try:
                    _wait_until(lambda: downgrade.done() or drop_ready.is_set())
                    release_writer.set()
                    if drop_ready.is_set():
                        assert writer_lookup.wait(10)
                        _wait_until(lambda: _blocked(engine, writer_pid[0]))
                finally:
                    release_writer.set()
                    release_drop.set()
                with pytest.raises(RuntimeError, match="0016 online downgrade is unsupported"):
                    downgrade.result(timeout=25)
                assert writer.result(timeout=25).status_code == 201
        finally:
            release_writer.set()
            release_drop.set()
            event.remove(engine, "after_cursor_execute", writer_after)
            event.remove(engine, "before_cursor_execute", writer_before)
            event.remove(Engine, "before_cursor_execute", migration_before)
    _assert_preserved(before_snapshot, retention_snapshot(engine))
    assert counts(engine) == (1, 1, 0, 0)


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
