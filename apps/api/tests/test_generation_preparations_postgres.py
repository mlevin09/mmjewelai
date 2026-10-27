"""Critical B2 migration and concurrency proofs; never DDL an unverified database."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT, create_hierarchy
from disposable_postgres import verified_ci_postgres
from jewelai_persistence import create_database_engine
from jewelai_persistence.models import GenerationCommandRow, GenerationPreparationRow
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_effective_readiness import _answer, _correct
from test_effective_readiness import ready_session as ready_session
from test_generation_preparations import counts, expected, post
from test_generation_preparations import (
    test_persistence_fault_rolls_back_artifact_and_command as _rollback,
)
from test_prompt_enrichment_http import _client


@pytest.fixture
def engine(monkeypatch, capfd):
    if os.getenv("GITHUB_ACTIONS") != "true":
        pytest.skip(
            "NOT VERIFIED locally: B2 requires independently verified disposable PostgreSQL"
        )
    # No SQL DDL, migration, drop_all or fixture setup occurs until this succeeds.
    url = verified_ci_postgres()
    control = create_database_engine(url)
    schema = "b2_" + uuid4().hex
    with control.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    scoped = create_database_engine(scoped_url.render_as_string(hide_password=False))
    monkeypatch.setenv("DATABASE_URL", scoped_url.render_as_string(hide_password=False))
    cfg = Config(str(ROOT / "packages/persistence/alembic.ini"))
    try:
        command.upgrade(cfg, "0015_reference_verification")
        # Insert an actual old session/revision before the additive upgrade, retain exact bytes.
        client, _ = _client(scoped)
        with client:
            org, _, old_session = create_hierarchy(client)
            sid = old_session.json()["session_id"]
            before = client.get(f"/sessions/{sid}", headers={"X-Organization-ID": org})
        with scoped.connect() as db:
            old_bytes = db.scalar(text("SELECT snapshot::text FROM specification_revision LIMIT 1"))
        command.upgrade(cfg, "head")
        command.check(cfg)
        command.current(cfg)
        # Empty B2 tables may roll back; historical session/revision rows remain untouched.
        command.downgrade(cfg, "0015_reference_verification")
        command.upgrade(cfg, "head")
        command.check(cfg)
        with scoped.connect() as db:
            assert (
                db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0016_generation_preparations"
            )
            assert (
                db.scalar(text("SELECT snapshot::text FROM specification_revision LIMIT 1"))
                == old_bytes
            )
        client, _ = _client(scoped)
        with client:
            after = client.get(f"/sessions/{sid}", headers={"X-Organization-ID": org})
        assert after.status_code == 200 and after.json() == before.json()
        with capfd.disabled():
            print(
                "B2_DISPOSABLE_POSTGRES: container/cluster verified; "
                "upgrade/check/current PASS; old revision bytes unchanged",
                flush=True,
            )
        yield scoped
    finally:
        scoped.dispose()
        # Only our validated, randomly named, newly created schema; never shared tables/databases.
        with control.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def test_same_revision_c3_to_c4_no_halo_race(ready_session, engine, capfd):
    ctx = ready_session()
    _correct(ctx, "Keep the white metal unchanged.")
    _correct(ctx, "Keep the oval center stone unchanged.")
    c3 = expected(ctx)
    assert c3["expected_enrichment_cycle_number"] == 3
    captured, resume = Event(), Event()

    def t1():
        captured.set()
        assert resume.wait(30)
        return post(ctx, c3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(t1)
        assert captured.wait(10)
        _correct(ctx, "Do not add a halo.")
        c4 = expected(ctx)
        resume.set()
        stale = pending.result(timeout=30)
    assert c4["expected_revision_id"] == c3["expected_revision_id"]
    assert c4["expected_enrichment_cycle_number"] == 4
    assert stale.status_code == 409 and stale.json()["error"] == "enrichment_cycle_mismatch"
    assert counts(engine) == (0, 0, 0, 0)
    with capfd.disabled():
        print(
            "B2_SYNTHETIC_RACE: "
            + json.dumps(
                {
                    "revision": c3["expected_revision_id"],
                    "captured_cycle": 3,
                    "committed_cycle": 4,
                    "status": stale.status_code,
                    "error": stale.json()["error"],
                    "preparation_rows": 0,
                    "command_rows": 0,
                },
                sort_keys=True,
            ),
            flush=True,
        )


def test_answer_frontier_and_concurrent_idempotency(ready_session, engine):
    ctx = ready_session()
    _correct(ctx, "I prefer yellow.")
    before = expected(ctx)
    _answer(ctx, "metal.color", decision="SKIP")
    current = expected(ctx)
    assert current["expected_revision_id"] == before["expected_revision_id"]
    stale = {
        **current,
        "expected_decision_frontier_hash": before["expected_decision_frontier_hash"],
    }
    assert post(ctx, stale).status_code == 409
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: post(ctx, current, key), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()
    assert counts(engine) == (1, 1, 0, 0)


def test_postgres_immutability_and_scope_foreign_keys(ready_session, engine):
    ctx = ready_session()
    assert post(ctx).status_code == 201
    for model in (GenerationPreparationRow, GenerationCommandRow):
        with pytest.raises(DBAPIError, match="immutable_generation_input"):
            with engine.begin() as db:
                db.execute(update(model).values(session_id=uuid4()))
    with engine.connect() as db:
        row = db.execute(select(GenerationCommandRow)).mappings().one()
        forged = dict(row)
    forged["organization_id"] = uuid4()
    forged["idempotency_key"] = uuid4()
    with pytest.raises(IntegrityError):
        with engine.begin() as db:
            db.execute(GenerationCommandRow.__table__.insert().values(**forged))
    with engine.connect() as db:
        retained = dict(db.execute(select(GenerationPreparationRow)).mappings().one())
    for field in (
        "organization_id",
        "project_id",
        "session_id",
        "design_id",
        "product_state_revision_id",
        "enrichment_cycle_id",
        "enrichment_cycle_number",
        "artifact_hash",
    ):
        invalid = {**retained, "preparation_id": uuid4()}
        invalid[field] = (
            retained[field] + 1
            if field == "enrichment_cycle_number"
            else "invalid"
            if field == "artifact_hash"
            else uuid4()
        )
        with pytest.raises(IntegrityError):
            with engine.begin() as db:
                db.execute(GenerationPreparationRow.__table__.insert().values(**invalid))
    assert counts(engine) == (1, 1, 0, 0)
    with pytest.raises(RuntimeError, match="Populated preparation history"):
        command.downgrade(
            Config(str(ROOT / "packages/persistence/alembic.ini")), "0015_reference_verification"
        )
    assert counts(engine) == (1, 1, 0, 0)


def test_postgres_command_failure_rolls_back_both_rows(ready_session, engine):
    _rollback(ready_session, engine)


def test_membership_revoked_after_http_check_is_rechecked_in_transaction(
    ready_session, engine, monkeypatch
):
    import jewelai_api.generation_preparations as service

    ctx = ready_session()
    member = ctx.client.get("/me", headers={"Authorization": "Bearer test-b2-member"}).json()
    membership = f"/organizations/{ctx.org}/memberships"
    assert (
        ctx.client.post(
            membership, json={"principal_id": member["principal_id"], "role": "member"}
        ).status_code
        == 201
    )
    request = expected(ctx)
    checked, resume = Event(), Event()
    commit = service.commit_preparation

    def pause_after_http_auth(*args, **kwargs):
        checked.set()
        assert resume.wait(30)
        return commit(*args, **kwargs)

    monkeypatch.setattr(service, "commit_preparation", pause_after_http_auth)
    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(
            ctx.client.post,
            f"/sessions/{ctx.sid}/generation-preparations",
            headers={
                **ctx.headers,
                "Authorization": "Bearer test-b2-member",
                "Idempotency-Key": str(uuid4()),
            },
            json=request,
        )
        assert checked.wait(10)
        assert ctx.client.delete(f"{membership}/{member['principal_id']}").status_code == 204
        resume.set()
        denied = response.result(timeout=30)
    assert denied.status_code == 404
    assert counts(engine) == (0, 0, 0, 0)
