"""Authoritative preparation, not generation; all identities/releases are synthetic."""

from uuid import uuid4

import pytest
from conftest import create_hierarchy
from jewelai_persistence.models import (
    GenerationCommandRow,
    GenerationDispatchOutboxRow,
    GenerationPreparationRow,
    GenerationRunRow,
)
from jewelai_prompts import GenerationPreparation
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError
from test_effective_readiness import _answer, _correct
from test_effective_readiness import ready_session as ready_session


def expected(ctx):
    response = ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
    )
    assert response.status_code == 200
    return response.json()["preparation_expectations"]


def post(ctx, request=None, key=None, **extra):
    return ctx.client.post(
        f"/sessions/{ctx.sid}/generation-preparations",
        headers={**ctx.headers, "Idempotency-Key": str(key or uuid4())},
        json={**(expected(ctx) if request is None else request), **extra},
    )


def counts(engine):
    with engine.connect() as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (
                GenerationPreparationRow,
                GenerationCommandRow,
                GenerationRunRow,
                GenerationDispatchOutboxRow,
            )
        )


def test_authoritative_no_halo_preparation_is_immutable_scoped_and_does_not_dispatch(
    ready_session, engine, monkeypatch
):
    ctx = ready_session()
    _correct(ctx, "Do not add a halo.")

    def forbidden(*args, **kwargs):
        pytest.fail("Preparation called the legacy compiler")

    monkeypatch.setattr("jewelai_api.services.compile_prompt", forbidden)
    monkeypatch.setattr("jewelai_prompts.compiler.compile_prompt", forbidden)
    response = post(ctx)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert set(body) == {
        "schema_version",
        "preparation_id",
        "session_id",
        "product_state_revision_id",
        "enrichment_cycle_id",
        "enrichment_cycle_number",
        "source_handoff_hash",
        "artifact_hash",
        "rendering_hash",
        "readiness",
        "unresolved_summary",
        "created_at",
    }
    assert counts(engine) == (1, 1, 0, 0)
    with engine.connect() as db:
        data = db.scalar(select(GenerationPreparationRow.artifact_bytes))
    artifact = GenerationPreparation(data)
    text = artifact.payload.execution.rendering_text
    prohibition = next(
        item
        for item in artifact.payload.source_handoff.internal_final_prompt.constraints
        if item.target == "feature.halo"
    )
    assert "PROHIBITION feature.halo" in text and prohibition.instruction in text
    assert artifact.payload.gate_evidence.release_verified
    assert ctx.provider.calls == []
    read = ctx.client.get(
        f"/sessions/{ctx.sid}/generation-preparations/{body['preparation_id']}", headers=ctx.headers
    )
    assert read.status_code == 200 and read.json() == body


def test_idempotent_replay_conflict_and_stale_cycle_are_distinct(ready_session, engine):
    ctx = ready_session()
    request, key = expected(ctx), uuid4()
    first = post(ctx, request, key)
    assert first.status_code == 201
    assert post(ctx, request, key).json() == first.json()
    assert post(ctx, {**request, "expected_handoff_hash": "0" * 64}, key).status_code == 409
    _correct(ctx, "Do not add a halo.")
    current = expected(ctx)
    assert current["expected_revision_id"] == request["expected_revision_id"]
    assert current["expected_enrichment_cycle_id"] != request["expected_enrichment_cycle_id"]
    replay = post(ctx, request, key)
    assert replay.status_code == 200 and replay.json() == first.json()
    stale = post(ctx, request)
    assert stale.status_code == 409 and stale.json()["error"] == "enrichment_cycle_mismatch"
    assert counts(engine) == (1, 1, 0, 0)


@pytest.mark.parametrize(
    "field,code",
    [
        ("expected_revision_id", "stale_revision"),
        ("expected_enrichment_result_hash", "enrichment_cycle_mismatch"),
        ("expected_enrichment_cycle_id", "enrichment_cycle_mismatch"),
        ("expected_clarification_plan_hash", "stale_clarification_plan"),
        ("expected_decision_frontier_hash", "stale_clarification_plan"),
        ("expected_handoff_hash", "preparation_stale"),
    ],
)
def test_each_expected_binding_fails_closed(ready_session, engine, field, code):
    ctx = ready_session()
    request = expected(ctx)
    request[field] = str(uuid4()) if field.endswith("_id") else "0" * 64
    response = post(ctx, request)
    assert response.status_code == 409 and response.json()["error"] == code
    assert counts(engine) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "extra", [{"release_verified": True}, {"handoff": {}}, {"rendering_text": "forged"}]
)
def test_client_cannot_supply_authority(ready_session, engine, extra):
    ctx = ready_session()
    assert post(ctx, **extra).status_code == 422
    assert counts(engine) == (0, 0, 0, 0)


def test_blocking_unknown_cannot_prepare(ready_session, engine):
    ctx = ready_session(missing_dimensions=True)
    response = post(ctx)
    assert response.status_code == 409 and response.json()["error"] == "final_output_not_ready"
    assert counts(engine) == (0, 0, 0, 0)


def test_persistence_fault_rolls_back_artifact_and_command(ready_session, engine):
    ctx = ready_session()

    def fault(*args):
        raise IntegrityError("synthetic-command-write-fault", {}, Exception("synthetic"))

    event.listen(GenerationCommandRow, "before_insert", fault)
    try:
        response = post(ctx)
    finally:
        event.remove(GenerationCommandRow, "before_insert", fault)
    assert response.status_code == 503
    assert response.json()["error"] == "generation_preparation_unavailable"
    assert counts(engine) == (0, 0, 0, 0)


def test_cross_session_org_membership_missing_key_and_no_dispatch_route(ready_session, engine):
    ctx = ready_session()
    first = post(ctx)
    assert first.status_code == 201
    pid = first.json()["preparation_id"]
    org, _, other = create_hierarchy(ctx.client)
    path = f"/sessions/{ctx.sid}/generation-preparations/{pid}"
    assert ctx.client.get(path, headers={"X-Organization-ID": org}).status_code == 404
    assert (
        ctx.client.get(
            f"/sessions/{other.json()['session_id']}/generation-preparations/{pid}",
            headers={"X-Organization-ID": org},
        ).status_code
        == 404
    )
    ctx.client.headers["Authorization"] = "Bearer test-outsider"
    assert ctx.client.get(path, headers=ctx.headers).status_code == 404
    ctx.client.headers["Authorization"] = "Bearer test-owner-a"
    assert (
        ctx.client.post(
            f"/sessions/{ctx.sid}/generation-preparations", headers=ctx.headers, json=expected(ctx)
        ).status_code
        == 422
    )
    assert (
        ctx.client.post(
            f"/sessions/{ctx.sid}/visualization-iterations",
            headers=ctx.headers,
            json={"schema_version": "2.0.0", "preparation_id": pid},
        ).status_code
        == 422
    )
    assert counts(engine) == (1, 1, 0, 0)


def test_tampered_storage_is_not_accepted_by_readback(ready_session, engine):
    ctx = ready_session()
    first = post(ctx)
    assert first.status_code == 201
    with engine.begin() as db:
        db.execute(update(GenerationPreparationRow).values(artifact_payload={"forged": True}))
    read = ctx.client.get(
        f"/sessions/{ctx.sid}/generation-preparations/{first.json()['preparation_id']}",
        headers=ctx.headers,
    )
    assert read.status_code == 500 and read.json()["error"] == "invalid_durable_history"


def test_answer_frontier_hash_is_checked_independently_of_cycle(ready_session, engine):
    ctx = ready_session()
    _correct(ctx, "I prefer yellow.")
    before = expected(ctx)
    _answer(ctx, "metal.color", decision="SKIP")
    current = expected(ctx)
    assert current["expected_revision_id"] == before["expected_revision_id"]
    assert current["expected_decision_frontier_hash"] != before["expected_decision_frontier_hash"]
    current["expected_decision_frontier_hash"] = before["expected_decision_frontier_hash"]
    response = post(ctx, current)
    assert response.status_code == 409 and response.json()["error"] == "stale_clarification_plan"
    assert counts(engine) == (0, 0, 0, 0)


def test_actual_knowledge_runtime_tamper_fails_before_any_write(ready_session, engine):
    ctx = ready_session()
    request = expected(ctx)
    runtime_path = (
        ctx.store.root / ctx.active.package_id / ctx.active.artifact_version / "runtime.json"
    )
    runtime_path.write_bytes(runtime_path.read_bytes() + b" ")
    response = post(ctx, request)
    assert response.status_code == 503
    assert response.json()["error"] == "knowledge_release_unavailable"
    assert str(runtime_path) not in response.text
    assert counts(engine) == (0, 0, 0, 0)


@pytest.mark.parametrize("code", ["unsupported_source_semantics", "preparation_capacity_exceeded"])
def test_renderer_failure_is_typed_redacted_and_atomic(ready_session, engine, monkeypatch, code):
    from jewelai_prompts import GenerationPreparationError, PreparationErrorCode

    ctx = ready_session()
    request = expected(ctx)

    def fail(*args, **kwargs):
        raise GenerationPreparationError(PreparationErrorCode(code))

    monkeypatch.setattr("jewelai_api.generation_preparations.build_generation_preparation", fail)
    response = post(ctx, request)
    assert response.status_code == 422 and response.json()["error"] == code
    assert counts(engine) == (0, 0, 0, 0)


def test_missing_bearer_and_member_revocation_prevent_replay(ready_session, engine):
    ctx = ready_session()
    member = ctx.client.get("/me", headers={"Authorization": "Bearer test-preparer"}).json()
    membership = f"/organizations/{ctx.org}/memberships"
    assert (
        ctx.client.post(
            membership, json={"principal_id": member["principal_id"], "role": "member"}
        ).status_code
        == 201
    )
    request, key = expected(ctx), uuid4()
    path = f"/sessions/{ctx.sid}/generation-preparations"
    headers = {**ctx.headers, "Authorization": "Bearer test-preparer", "Idempotency-Key": str(key)}
    first = ctx.client.post(path, headers=headers, json=request)
    assert first.status_code == 201
    assert ctx.client.delete(f"{membership}/{member['principal_id']}").status_code == 204
    assert ctx.client.post(path, headers=headers, json=request).status_code == 404
    assert (
        ctx.client.get(f"{path}/{first.json()['preparation_id']}", headers=headers).status_code
        == 404
    )
    assert (
        ctx.client.post(path, headers={**headers, "Authorization": ""}, json=request).status_code
        == 401
    )
    assert counts(engine) == (1, 1, 0, 0)
