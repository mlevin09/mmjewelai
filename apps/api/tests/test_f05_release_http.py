"""Persisted typed consent, one-field provenance, duplicate CAS and restart."""

from uuid import uuid4

import pytest
from test_f04_http import f04_session, restart
from test_f05_admission import admit, rows
from test_f05_history import initial
from test_prompt_enrichment_http import _message


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_release_http(engine, tmp_path, base, decision):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        admitted, _ = admit(ctx)
        assert admitted.status_code == 201, admitted.json()
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        message = _message(ctx.client, str(ctx.sid), str(ctx.org), "Emerald cut center stone.")
        correction = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                request_id=str(uuid4()),
                message_id=message["message_id"],
                expected_head=admitted.json()["current_state"]["current_frame"],
            ),
        )
        assert correction.status_code == 200, correction.json()
        state = correction.json()["current_state"]
        question = next(
            q["offer"] for q in state["questions"] if q["question_kind"] == "KEEP_RELEASE"
        )
        consent = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit scoped synthetic consent."
        )
        payload = dict(
            schema_version="3.0.0",
            answer_kind="KEEP_RELEASE",
            answer_id=str(uuid4()),
            message_id=consent["message_id"],
            expected_head=state["current_frame"],
            clarification_plan_id=state["current_frame"]["plan_id"],
            clarification_id=question["offer_id"],
            intent_id=question["intent_id"],
            requested_value_sha256=question["requested_value_sha256"],
            decision=decision,
        )
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers"
        response = ctx.client.post(path, headers=ctx.headers, json=payload)
        assert response.status_code == 200, response.json()
        new = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert new.design.center_stone.shape.value == (
            "emerald_cut" if decision == "ACCEPT" else "oval"
        )
        for name in type(before.design.center_stone).model_fields:
            if name != "shape":
                assert getattr(new.design.center_stone, name) == getattr(
                    before.design.center_stone, name
                )
        if decision == "ACCEPT":
            assert new.design.center_stone.shape.source.message_id == message["message_id"]
            assert new.event.source.message_id == consent["message_id"]
        committed = rows(ctx)
        repeated = ctx.client.post(path, headers=ctx.headers, json=payload)
        assert repeated.status_code == 200, repeated.json()
        assert repeated.json()["replayed"] is True
        assert rows(ctx) == committed
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            current = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert current.status_code == 200, current.json()
            assert current.json() == response.json()["current_state"]


@pytest.mark.parametrize("base", ["L", "F"])
def test_resume_rebinds_only_requested_pending_intent(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        admitted, _ = admit(ctx)
        state = admitted.json()["current_state"]
        for text in ("Emerald cut center stone.", "A white gold ring."):
            message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
            result = ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
                headers=ctx.headers,
                json=dict(
                    schema_version="3.0.0",
                    request_id=str(uuid4()),
                    message_id=message["message_id"],
                    expected_head=state["current_frame"],
                ),
            )
            assert result.status_code == 200, result.json()
            state = result.json()["current_state"]
        pending = state["protection_projection"]["pending_requests"]
        assert len(pending) == 1 and pending[0]["status"] == "RECONFIRMATION_REQUIRED"
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicitly resume the pending request."
        )
        payload = dict(
            schema_version="3.0.0",
            resume_kind="KEEP_RELEASE",
            intent_id=pending[0]["intent_id"],
            request_id=str(uuid4()),
            message_id=message["message_id"],
            expected_head=state["current_frame"],
        )
        path = (
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarifications/"
            f"{pending[0]['intent_id']}/resume"
        )
        result = ctx.client.post(path, headers=ctx.headers, json=payload)
        assert result.status_code == 200, result.json()
        updated = result.json()["current_state"]
        assert updated["protection_projection"]["pending_requests"][0]["status"] == "PENDING"
        assert (
            next(q["offer"] for q in updated["questions"] if q["question_kind"] == "KEEP_RELEASE")[
                "binding"
            ]["previous_offer_ref"]
            is not None
        )
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "oval"
        )
        committed = rows(ctx)
        again = ctx.client.post(path, headers=ctx.headers, json=payload)
        assert again.status_code == 200 and again.json()["replayed"], again.json()
        assert rows(ctx) == committed
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            read = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert read.status_code == 200, read.json()
            assert read.json() == updated


@pytest.mark.parametrize("base", ["L", "F"])
def test_new_specific_root_does_not_cancel_generic_root(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        admitted, _ = admit(ctx)
        state = admitted.json()["current_state"]
        old_ids = {r["root_ref"]["evidence_id"] for r in state["protection_projection"]["roots"]}
        source = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Keep the center stone shape unchanged."
        )
        result = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                request_id=str(uuid4()),
                message_id=source["message_id"],
                expected_head=state["current_frame"],
            ),
        )
        assert result.status_code == 200, result.json()
        state = result.json()["current_state"]
        roots = state["protection_projection"]["roots"]
        assert len(roots) == 2 and old_ids.issubset({r["root_ref"]["evidence_id"] for r in roots})
        assert sorted(len(r["scope_targets"]) for r in roots) == [1, 8]
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            read = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert read.status_code == 200, read.json()
            assert read.json() == state


def pending_fixture(ctx, base, text="Emerald cut center stone."):
    initial(ctx, base)
    ctx.runtime.continuation_enabled = True
    admission, _ = admit(ctx)
    assert admission.status_code == 201, admission.json()
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    r = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
        headers=ctx.headers,
        json=dict(
            schema_version="3.0.0",
            request_id=str(uuid4()),
            message_id=message["message_id"],
            expected_head=admission.json()["current_state"]["current_frame"],
        ),
    )
    assert r.status_code == 200, r.json()
    current = r.json()["current_state"]
    return current, next(
        q["offer"] for q in current["questions"] if q["question_kind"] == "KEEP_RELEASE"
    )


def consent_payload(ctx, state, offer, decision):
    msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic scoped decision.")
    return dict(
        schema_version="3.0.0",
        answer_kind="KEEP_RELEASE",
        answer_id=str(uuid4()),
        message_id=msg["message_id"],
        expected_head=state["current_frame"],
        clarification_plan_id=state["current_frame"]["plan_id"],
        clarification_id=offer["offer_id"],
        intent_id=offer["intent_id"],
        requested_value_sha256=offer["requested_value_sha256"],
        decision=decision,
    )


@pytest.mark.parametrize("base", ["L", "F"])
def test_release_plan_insert_failure_rolls_back_revision_answer_and_cycle(engine, tmp_path, base):
    from sqlalchemy import event

    with f04_session(engine, tmp_path) as ctx:
        current, offer = pending_fixture(ctx, base)
        payload = consent_payload(ctx, current, offer, "ACCEPT")
        before = rows(ctx)

        def fail(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("INSERT INTO CLARIFICATION_PLAN"):
                raise RuntimeError("Synthetic Plan3 fault")

        event.listen(engine, "before_cursor_execute", fail)
        try:
            result = ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
                headers=ctx.headers,
                json=payload,
            )
        finally:
            event.remove(engine, "before_cursor_execute", fail)
        assert result.status_code == 500
        assert rows(ctx) == before
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "oval"
        )


def correction_payload(ctx, current, text):
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    return dict(
        schema_version="3.0.0",
        request_id=str(uuid4()),
        message_id=message["message_id"],
        expected_head=current["current_frame"],
    )


def correct3(ctx, current, text):
    payload = correction_payload(ctx, current, text)
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections", headers=ctx.headers, json=payload
    )
    assert response.status_code == 200, response.json()
    return response.json()["current_state"]


def answer3(ctx, current, offer, decision):
    payload = consent_payload(ctx, current, offer, decision)
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
        headers=ctx.headers,
        json=payload,
    )
    assert response.status_code == 200, response.json()
    return response.json()["current_state"]


@pytest.mark.parametrize("base", ["L", "F"])
def test_two_same_field_intents_survive_accept_until_explicit_reject_closure(
    engine, tmp_path, base
):
    from test_f05_preview import output, state

    with f04_session(engine, tmp_path) as ctx:
        current, first = pending_fixture(ctx, base)
        current = correct3(ctx, current, "Emerald cut center stone.")
        second = next(
            q["offer"] for q in current["questions"] if q["question_kind"] == "KEEP_RELEASE"
        )
        assert first["intent_id"] != second["intent_id"]
        assert len(current["protection_projection"]["pending_requests"]) == 2
        current = answer3(ctx, current, second, "ACCEPT")
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "emerald_cut"
        )
        remaining = current["protection_projection"]["pending_requests"]
        assert len(remaining) == 1 and remaining[0]["intent_id"] == first["intent_id"]
        assert output(ctx, current, projection=base == "L").status_code == 409
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit pending intent resume.")
        payload = dict(
            schema_version="3.0.0",
            resume_kind="KEEP_RELEASE",
            intent_id=first["intent_id"],
            request_id=str(uuid4()),
            message_id=msg["message_id"],
            expected_head=current["current_frame"],
        )
        response = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarifications/{first['intent_id']}/resume",
            headers=ctx.headers,
            json=payload,
        )
        assert response.status_code == 200, response.json()
        current = response.json()["current_state"]
        offer = next(
            q["offer"] for q in current["questions"] if q["question_kind"] == "KEEP_RELEASE"
        )
        assert offer["allowed_decisions"] == ["REJECT"]
        wrong = consent_payload(ctx, current, offer, "ACCEPT")
        before = rows(ctx)
        denied = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=wrong,
        )
        assert (
            denied.status_code == 409 and denied.json()["error"] == "intent_no_longer_applicable"
        ), denied.json()
        assert rows(ctx) == before
        current = answer3(ctx, current, offer, "REJECT")
        assert not current["protection_projection"]["pending_requests"]
        final = output(ctx, current, projection=base == "L")
        assert final.status_code == 200, final.json()
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
            assert output(ctx, current, projection=base == "L").json() == final.json()
