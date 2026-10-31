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
from test_core_intent import (
    C1_CASES,
    REVIEW_RU,
    exercise_core_case,
    exercise_core_lifecycle,
)
from test_core_intent import (
    test_core_confirmed_material_http as _core_confirmed,
)
from test_core_intent import (
    test_core_locked_material_cannot_be_replaced as _core_locked,
)
from test_core_intent import (
    test_core_style_description_http as _core_style,
)
from test_core_intent import (
    test_review_ru_preference_and_correction_http as _core_ru_correction,
)
from test_effective_readiness import _answer, _correct
from test_effective_readiness import ready_session as ready_session
from test_generation_preparations import counts, expected, post
from test_generation_preparations import (
    test_persistence_fault_rolls_back_artifact_and_command as _rollback,
)
from test_p010_symmetry_runtime import (
    F00_INDEPENDENT_METAL,
    F00_LIFECYCLES,
    F00_NEGATIVE_LISTS,
    KEEP_COMPATIBLE_FULL_CORRECTIONS,
    KEEP_FOLLOWUPS,
    REVIEW_NEGATIVES,
    SCOPE_CONTROLS,
    SCOPE_REVIEW_CASES,
    exercise_keep_correction_sequence,
    exercise_p010_rejected_http,
)
from test_p010_symmetry_runtime import (
    test_f00_unresolved_request_does_not_make_accepted_fact_ambiguous as _unresolved_request,
)
from test_pr133_review_regressions import assert_preparation_roundtrip
from test_prompt_enrichment_http import _client


@pytest.mark.parametrize("binding", (False, True))
@pytest.mark.parametrize("case", C1_CASES, ids=[c[0] for c in C1_CASES])
def test_c1_intent_http_postgres(engine, tmp_path, monkeypatch, case, binding):
    exercise_core_case(engine, tmp_path, monkeypatch, case, binding)


@pytest.mark.parametrize("binding", (False, True))
def test_c1_six_cycle_postgres(engine, tmp_path, monkeypatch, binding):
    exercise_core_lifecycle(engine, tmp_path, monkeypatch, binding)


@pytest.mark.parametrize("binding", (False, True))
def test_c1_coordinated_six_cycle_postgres(engine, tmp_path, monkeypatch, binding):
    exercise_core_lifecycle(engine, tmp_path, monkeypatch, binding, coordinated=True)


@pytest.mark.parametrize("binding", (False, True))
@pytest.mark.parametrize("text", REVIEW_RU)
def test_c1_ru_correction_postgres(engine, tmp_path, monkeypatch, binding, text):
    _core_ru_correction(engine, tmp_path, monkeypatch, binding, text)


@pytest.mark.parametrize("locale", ("en", "ru"))
def test_c1_style_description_postgres(engine, tmp_path, monkeypatch, locale):
    _core_style(engine, tmp_path, monkeypatch, locale)


@pytest.mark.parametrize("binding", (False, True))
def test_c1_confirmed_authority_postgres(engine, tmp_path, monkeypatch, binding):
    _core_confirmed(engine, tmp_path, monkeypatch, binding)


def test_c1_locked_authority_postgres(engine, tmp_path, monkeypatch):
    _core_locked(engine, tmp_path, monkeypatch)


def test_p010_original_raw_message_lifecycle_postgres(engine, tmp_path, monkeypatch):
    from test_p010_symmetry_runtime import exercise_p010_http

    exercise_p010_http(engine, tmp_path, monkeypatch)


@pytest.mark.parametrize("text", REVIEW_NEGATIVES)
def test_p010_rejected_raw_message_postgres(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text)


@pytest.mark.parametrize(
    "text,symmetry,keep,halo",
    SCOPE_REVIEW_CASES + tuple(case for case in SCOPE_CONTROLS if all(case[1:])),
)
def test_p010_semantic_scope_postgres(engine, tmp_path, monkeypatch, text, symmetry, keep, halo):
    exercise_p010_rejected_http(
        engine, tmp_path, monkeypatch, text, symmetry=symmetry, keep=keep, halo=halo
    )


@pytest.mark.parametrize("text", F00_NEGATIVE_LISTS)
def test_f00_negative_lists_postgres(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text)


@pytest.mark.parametrize("text,symmetry,keep,halo", F00_LIFECYCLES)
def test_f00_functional_ifp_postgres(engine, tmp_path, monkeypatch, text, symmetry, keep, halo):
    exercise_p010_rejected_http(
        engine, tmp_path, monkeypatch, text, symmetry=symmetry, keep=keep, halo=halo, finish=True
    )


@pytest.mark.parametrize("text", F00_INDEPENDENT_METAL)
def test_f00_independent_dictionary_facts_postgres(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text, symmetry=True, metal=True)


def test_f00_unresolved_same_target_postgres(engine, tmp_path, monkeypatch):
    _unresolved_request(engine, tmp_path, monkeypatch)


@pytest.mark.parametrize("followups", KEEP_FOLLOWUPS)
def test_f00_keep_corrections_postgres(engine, tmp_path, monkeypatch, followups):
    exercise_keep_correction_sequence(engine, tmp_path, monkeypatch, followups)


@pytest.mark.parametrize("correction", KEEP_COMPATIBLE_FULL_CORRECTIONS)
def test_f00_keep_three_cycles_postgres(engine, tmp_path, monkeypatch, correction):
    exercise_p010_rejected_http(
        engine,
        tmp_path,
        monkeypatch,
        "Асимметричное кольцо — не выравнивай его.",
        symmetry=True,
        keep=True,
        finish=True,
        finish_correction_text=correction,
    )


def test_f00_keep_authority_postgres(engine, tmp_path, monkeypatch):
    exercise_keep_correction_sequence(engine, tmp_path, monkeypatch, (), external_edit=True)


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
    scoped_url = _schema_url(url, schema)
    scoped = create_database_engine(scoped_url)
    monkeypatch.setenv("DATABASE_URL", scoped_url)
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
        # Unsupported online downgrade refuses even with empty retained tables.
        retained = retention_snapshot(scoped)
        with pytest.raises(RuntimeError, match="online downgrade is unsupported"):
            command.downgrade(cfg, "0015_reference_verification")
        assert retention_snapshot(scoped) == retained
        command.check(cfg)
        with scoped.connect() as db:
            assert (
                db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0017_knowledge_release_bindings"
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


def _schema_url(url, schema):
    # Only our generated ASCII identifier is used. Leave '=' unescaped to preserve the URL
    # through existing Alembic ConfigParser interpolation without altering shared env.py.
    assert schema.startswith("b2_") and len(schema) == 35
    assert all(c in "0123456789abcdef" for c in schema[3:])
    return url + "?options=-csearch_path=" + schema


def retention_snapshot(engine):
    """Exact retained bytes/hashes and schema objects; never print synthetic source payloads."""
    with engine.connect() as db:
        objects = tuple(
            db.execute(
                text("""
            SELECT 'relation', c.relname, c.relkind::text FROM pg_class c
              JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema()
            UNION ALL
            SELECT 'constraint', c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c
              JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname=current_schema()
            UNION ALL
            SELECT 'trigger', t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t
              JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname=current_schema() AND NOT t.tgisinternal
            UNION ALL
            SELECT 'function', p.proname, pg_get_functiondef(p.oid) FROM pg_proc p
              JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=current_schema()
            ORDER BY 1,2,3
        """)
            )
        )
        rows = {
            model.__tablename__: tuple(
                dict(row)
                for row in db.execute(
                    select(model).order_by(*model.__table__.primary_key.columns)
                ).mappings()
            )
            for model in (GenerationPreparationRow, GenerationCommandRow)
        }
        return {
            "version": db.scalar(text("SELECT version_num FROM alembic_version")),
            "objects": objects,
            "rows": rows,
        }


def test_scoped_url_preserves_driver_options_and_alembic_interpolation():
    url = _schema_url("postgresql+psycopg://localhost/jewelai_test", "b2_" + "a" * 32)
    assert make_url(url).query["options"] == "-csearch_path=b2_" + "a" * 32
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", url)
    assert cfg.get_main_option("sqlalchemy.url") == url


def test_knowledge_binding_preparation_post_get_replay(ready_session, engine):
    # Same durability assertions on verified PostgreSQL; not a claim of the SQLite defect there.
    assert_preparation_roundtrip(ready_session(), engine)


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
    before = retention_snapshot(engine)
    with pytest.raises(RuntimeError, match="online downgrade is unsupported"):
        command.downgrade(
            Config(str(ROOT / "packages/persistence/alembic.ini")), "0015_reference_verification"
        )
    assert counts(engine) == (1, 1, 0, 0)
    assert retention_snapshot(engine) == before


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
