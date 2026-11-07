"""Session retirement PostgreSQL migration, retention and transaction regressions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import NOW, ROOT, create_hierarchy
from jewelai_persistence.models import DesignSessionRow, GenerationRunRow
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import IntegrityError
from test_api import complete_iteration_run, create_ready_prompt
from test_generation_preparations_postgres import engine as engine
from test_session_retirement import (
    test_retirement_authentication_cross_tenant_and_unknown_session as _scope,
)
from test_session_retirement import (
    test_retirement_blocks_active_generation_and_preserves_outbox as _active,
)
from test_session_retirement import (
    test_retirement_preserves_completed_native_history_and_restart as _history,
)
from test_session_retirement import (
    test_retirement_requires_owner_or_admin_in_exact_organization as _role,
)
from test_session_retirement import (
    test_retirement_waits_for_successful_run_asset_finalization as _materialization,
)

pytestmark = pytest.mark.postgres


def test_pg01_migration_constraints_and_tombstone_downgrade(client, engine, monkeypatch):
    # engine has already verified real container/cluster and upgraded populated0015→head.
    org, _, created = create_hierarchy(client)
    sid = UUID(created.json()["session_id"])
    with engine.connect() as db:
        assert (
            db.scalar(text("SELECT version_num FROM alembic_version")) == "0020_session_retirement"
        )
        before = db.execute(
            select(DesignSessionRow.__table__).where(DesignSessionRow.session_id == sid)
        ).one()
    for values in ({"deleted_at": NOW}, {"deleted_at": NOW, "deleted_by_principal_id": uuid4()}):
        with pytest.raises(IntegrityError):
            with engine.begin() as db:
                db.execute(
                    update(DesignSessionRow)
                    .where(DesignSessionRow.session_id == sid)
                    .values(**values)
                )
        with engine.connect() as db:
            assert (
                db.execute(
                    select(DesignSessionRow.__table__).where(DesignSessionRow.session_id == sid)
                ).one()
                == before
            )
    assert client.delete(f"/sessions/{sid}", headers={"X-Organization-ID": org}).status_code == 204
    with engine.connect() as db:
        retired = db.execute(
            select(DesignSessionRow.__table__).where(DesignSessionRow.session_id == sid)
        ).one()
    cfg = Config(str(ROOT / "packages/persistence/alembic.ini"))
    with pytest.raises(RuntimeError, match="tombstones"):
        command.downgrade(cfg, "0019_prompt_completion")
    command.upgrade(cfg, "head")
    command.current(cfg)
    command.check(cfg)
    with engine.connect() as db:
        assert (
            db.execute(
                select(DesignSessionRow.__table__).where(DesignSessionRow.session_id == sid)
            ).one()
            == retired
        )


def test_pg02_history_idempotency_access_and_restart(engine, tmp_path, monkeypatch):
    _history(engine, tmp_path, monkeypatch)


@pytest.mark.parametrize("role,status", [("owner", 204), ("admin", 204), ("member", 403)])
def test_pg02_roles(client, role, status):
    _role(client, role, status)


def test_pg02_authentication_and_tenant_isolation(client):
    _scope(client)


@pytest.mark.parametrize("running", [False, True])
def test_retirement_active_generation_postgres(client, app, running):
    _active(client, app, running)


def test_retirement_asset_retention_postgres(client, app, engine):
    _materialization(client, app, engine)


@pytest.mark.parametrize("operation", ["new", "retry"])
@pytest.mark.parametrize("first", ["delete", "generation"])
def test_pg04_generation_lock_order(client, app, engine, operation, first):
    org, _, session, _, prompt = create_ready_prompt(client)
    sid = UUID(session["session_id"])
    path = f"/sessions/{sid}"
    headers = {"X-Organization-ID": org}
    url = path + "/generation-runs"
    body = {"prompt_revision_id": prompt["prompt_revision_id"], "profile_id": "test_default"}
    baseline = 0
    if operation == "retry":
        parent = client.post(url, headers=headers, json=body)
        assert parent.status_code == 201
        complete_iteration_run(app.state.service.repository, parent.json(), org, succeed=False)
        url += f"/{parent.json()['generation_run_id']}/retry"
        body = {}
        baseline = 1
    held, release, attempted = Event(), Event(), Event()
    paused = False

    def before(conn, cursor, statement, parameters, context, many):
        if "design_session" in statement and "FOR UPDATE" in statement and held.is_set():
            attempted.set()

    def after(conn, cursor, statement, parameters, context, many):
        nonlocal paused
        if "design_session" in statement and "FOR UPDATE" in statement and not paused:
            paused = True
            held.set()  # The first transaction has actually acquired the row lock.
            assert release.wait(20), "qualification lock release was not signalled"

    def generate():
        return client.post(url, headers=headers, json=body)

    def retire():
        return client.delete(path, headers=headers)

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_call, second_call = (
                (retire, generate) if first == "delete" else (generate, retire)
            )
            winner = pool.submit(first_call)
            try:
                assert held.wait(10)
                contender = pool.submit(second_call)
                assert attempted.wait(10), "competing operation did not reach the session lock"
            finally:
                release.set()
            a, b = winner.result(timeout=25), contender.result(timeout=25)
        assert (a.status_code, b.status_code) == ((204, 404) if first == "delete" else (201, 409))
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    with engine.connect() as db:
        row = db.execute(
            select(DesignSessionRow.deleted_at).where(DesignSessionRow.session_id == sid)
        ).one()
        runs = db.execute(
            select(GenerationRunRow.generation_run_id).where(GenerationRunRow.session_id == sid)
        ).all()
    assert bool(row.deleted_at) == (first == "delete")
    assert len(runs) == baseline + (first == "generation")
    if first == "delete":
        assert (
            client.post(
                path + "/messages", headers=headers, json={"content": "Synthetic late write"}
            ).status_code
            == 404
        )


def test_pg04_role_revoked_after_http_check(client, app, monkeypatch):
    org, _, created = create_hierarchy(client)
    headers = {"X-Organization-ID": org, "Authorization": "Bearer test-qualified-admin"}
    actor = client.get("/me", headers=headers).json()["principal_id"]
    membership = f"/organizations/{org}/memberships"
    assert client.post(membership, json={"principal_id": actor, "role": "admin"}).status_code == 201
    checked, release = Event(), Event()
    repo = app.state.service.repository
    original = repo.retire_design_session

    def pause(*args):
        checked.set()
        assert release.wait(20)
        return original(*args)

    monkeypatch.setattr(repo, "retire_design_session", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            client.delete, f"/sessions/{created.json()['session_id']}", headers=headers
        )
        try:
            assert checked.wait(10)
            assert (
                client.patch(membership + f"/{actor}", json={"role": "member"}).status_code == 200
            )
        finally:
            release.set()
        assert future.result(timeout=25).status_code == 403
    assert (
        client.get(f"/sessions/{created.json()['session_id']}", headers=headers).status_code == 200
    )


def test_pg04_transaction_fault_rolls_back(client, app, engine):
    org, _, created = create_hierarchy(client)
    sid = UUID(created.json()["session_id"])
    actor = UUID(client.get("/me").json()["principal_id"])
    repo = app.state.service.repository
    with engine.connect() as db:
        before = db.execute(
            select(DesignSessionRow.__table__).where(DesignSessionRow.session_id == sid)
        ).one()

    def fail_before_commit(db):
        if any(
            isinstance(row, DesignSessionRow) and row.deleted_at is not None for row in db.dirty
        ):
            raise RuntimeError("qualification injected pre-commit fault")

    event.listen(repo._session_factory.class_, "before_commit", fail_before_commit)
    try:
        with pytest.raises(RuntimeError, match="qualification injected"):
            repo.retire_design_session(sid, UUID(org), actor, NOW)
    finally:
        event.remove(repo._session_factory.class_, "before_commit", fail_before_commit)
    with engine.connect() as db:
        assert (
            db.execute(
                select(DesignSessionRow.__table__).where(DesignSessionRow.session_id == sid)
            ).one()
            == before
        )
    assert client.get(f"/sessions/{sid}", headers={"X-Organization-ID": org}).status_code == 200


def test_pg04_retirement_organization_lock_serializes_role_revocation(client, engine):
    org, _, created = create_hierarchy(client)
    headers = {"X-Organization-ID": org, "Authorization": "Bearer test-locking-admin"}
    actor = client.get("/me", headers=headers).json()["principal_id"]
    membership = f"/organizations/{org}/memberships"
    assert client.post(membership, json={"principal_id": actor, "role": "admin"}).status_code == 201
    held, attempted, release = Event(), Event(), Event()

    def before(conn, cursor, statement, parameters, context, many):
        if "FROM organization " in statement.replace("\n", " ") and "FOR UPDATE" in statement:
            attempted.set()

    def after(conn, cursor, statement, parameters, context, many):
        if (
            "FROM organization " in statement.replace("\n", " ")
            and "FOR NO KEY UPDATE" in statement
        ):
            held.set()
            assert release.wait(20)

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            deletion = pool.submit(
                client.delete, f"/sessions/{created.json()['session_id']}", headers=headers
            )
            try:
                assert held.wait(10)
                revocation = pool.submit(
                    client.patch, membership + f"/{actor}", json={"role": "member"}
                )
                assert attempted.wait(10)
            finally:
                release.set()
            assert deletion.result(timeout=25).status_code == 204
            assert revocation.result(timeout=25).status_code == 200
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    with engine.connect() as db:
        assert (
            str(
                db.scalar(
                    select(DesignSessionRow.deleted_by_principal_id).where(
                        DesignSessionRow.session_id == UUID(created.json()["session_id"])
                    )
                )
            )
            == actor
        )
