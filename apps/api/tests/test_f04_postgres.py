"""F04 real PostgreSQL proofs through the existing independent disposable-CI gate.

No local URL or naming convention authorizes DDL. The imported fixture verifies
container and cluster identity before creating its isolated, disposable schema.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from test_effective_readiness import ready_session as ready_session
from test_f04_http import (
    READY_TEXT,
    answer,
    correct,
    f04_session,
    initial,
    resume,
)
from test_f04_http import (
    test_f04_three_cycle_persisted_restoration_and_preparation_http as _lifecycle,
)
from test_generation_preparations import post
from test_generation_preparations_postgres import engine as engine
from test_generation_preparations_postgres import retention_snapshot


def receipt(capfd, kind, **evidence):
    with capfd.disabled():
        print(
            "F04_POSTGRES_RECEIPT " + json.dumps(dict(kind=kind, **evidence), sort_keys=True),
            flush=True,
        )


def test_f04_full_http_restart_preparation_postgres(engine, tmp_path, capfd):
    _lifecycle(engine, tmp_path)
    receipt(capfd, "three-cycle-http-restart-preparation", result="PASS", provider_calls=0)


@pytest.mark.parametrize("conflicting", [False, True])
def test_f04_concurrent_material_answers_postgres(engine, tmp_path, conflicting, capfd):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        # Capture a valid request without executing it, using the actual offered IDs.
        q = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "METAL_MATERIAL"
        )
        from test_prompt_enrichment_http import _message

        message = _message(ctx.client, str(ctx.sid), str(ctx.org), "Synthetic concurrent answer.")
        payload = dict(
            schema_version="2.0.0",
            clarification_plan_id=state["clarification_plan_id"],
            plan_content_hash=state["clarification_plan_content_hash"],
            clarification_id=q["clarification_id"],
            decision="SELECT_OPTION",
            selected_option="gold",
            selected_option_id=q["options"][0]["option_id"],
            expected_revision_id=state["authoritative_revision_id"],
            answer_id=str(uuid4()),
            message_id=message["message_id"],
        )
        other = {**payload, "answer_id": str(uuid4())}
        if conflicting:
            option = next(o for o in q["options"] if o["value"] == "platinum")
            other.update(selected_option=option["value"], selected_option_id=option["option_id"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda p: answer(ctx, state, request=p)[0], (payload, other)))
        assert sorted(r.status_code for r in results) == (
            [200, 409] if conflicting else [200, 200]
        ), [r.json() for r in results]
        assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == 2
        assert len(ctx.repo.list_clarification_answers(ctx.sid, ctx.org)) == 1
        if not conflicting:
            assert (
                results[0].json()["answer_content_hash"] == results[1].json()["answer_content_hash"]
            )


@pytest.mark.parametrize("conflicting", [False, True])
def test_f04_concurrent_resume_postgres(engine, tmp_path, conflicting, capfd):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        cause_id = next(
            q["cause_id"]
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "METAL_MATERIAL"
        )
        result, _ = answer(ctx, state, "SKIP")
        assert result.status_code == 200
        state = result.json()["state"]
        from test_prompt_enrichment_http import _message

        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Synthetic explicit concurrent resume."
        )
        cycle = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1]
        payload = dict(
            schema_version="1.0.0",
            request_id=str(uuid4()),
            message_id=message["message_id"],
            expected_revision_id=state["authoritative_revision_id"],
            expected_enrichment_cycle_id=state["enrichment_cycle_id"],
            expected_enrichment_result_hash=cycle.result.content_hash,
            expected_clarification_plan_hash=state["clarification_plan_content_hash"],
        )
        other = dict(payload)
        if conflicting:
            other["message_id"] = _message(
                ctx.client, str(ctx.sid), str(ctx.org), "Different concurrent resume."
            )["message_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda p: resume(ctx, state, cause_id, payload=p)[0], (payload, other))
            )
        assert sorted(r.status_code for r in results) == (
            [200, 409] if conflicting else [200, 200]
        ), [r.json() for r in results]
        assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == 3
        assert len(ctx.repo.list_clarification_answers(ctx.sid, ctx.org)) == 1
        receipt(
            capfd,
            "resume-race",
            conflicting=conflicting,
            statuses=sorted(r.status_code for r in results),
            cycles=3,
            answer_rows=1,
        )
        if not conflicting:
            assert results[0].json()["result"] == results[1].json()["result"]


@pytest.mark.parametrize("engine", ["0018_f04_preparation_v2"], indirect=True)
def test_f04_check_downgrade_retains_actual_preparation1_postgres(engine, ready_session, capfd):
    ctx = ready_session()
    assert post(ctx).status_code == 201
    before = retention_snapshot(engine)
    assert before["version"] == "0018_f04_preparation_v2"
    config = Config(str(ROOT / "packages/persistence/alembic.ini"))
    command.downgrade(config, "0017_knowledge_release_bindings")
    middle = retention_snapshot(engine)
    assert middle["rows"] == before["rows"]
    assert middle["version"] == "0017_knowledge_release_bindings"
    command.upgrade(config, "0018_f04_preparation_v2")
    assert retention_snapshot(engine) == before
    command.upgrade(config, "head")
    command.check(config)
    receipt(
        capfd, "0018-0017-0018-preparation1-retention", result="PASS", retained_rows_unchanged=True
    )


@pytest.mark.parametrize("engine", ["0018_f04_preparation_v2"], indirect=True)
def test_f04_check_downgrade_refuses_actual_preparation2_postgres(engine, tmp_path, capfd):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        response, _ = answer(ctx, state, "UNKNOWN")
        state = correct(ctx, response.json()["state"], "A platinum ring.")
        prepared = ctx.client.post(
            f"/sessions/{ctx.sid}/generation-preparations",
            headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
            json=state["preparation_expectations"],
        )
        assert prepared.status_code == 201, prepared.json()
        assert prepared.json()["schema_version"] == "2.0.0"
        before = retention_snapshot(engine)
        assert before["version"] == "0018_f04_preparation_v2"
        config = Config(str(ROOT / "packages/persistence/alembic.ini"))
        with pytest.raises(RuntimeError, match="prevent safe downgrade"):
            command.downgrade(config, "0017_knowledge_release_bindings")
        assert retention_snapshot(engine) == before
        command.upgrade(config, "head")
        command.check(config)
        receipt(
            capfd,
            "0018-preparation2-downgrade-refusal",
            result="PASS",
            retained_rows_unchanged=True,
        )


def test_f04_answer_failure_rolls_back_all_rows_postgres(engine, tmp_path, monkeypatch, capfd):
    from test_f04_http import test_f04_answer_fault_rolls_back_revision_cycle_and_decision

    test_f04_answer_fault_rolls_back_revision_cycle_and_decision(engine, tmp_path, monkeypatch)

    receipt(
        capfd, "answer-transaction-fault", result="PASS", revision_cycle_decision_rolled_back=True
    )
