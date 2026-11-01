"""All five ordinary native actions exercise the actual admitted writer."""

from uuid import uuid4

import pytest
from test_f04_http import f04_session, restart
from test_f05_admission import admit, rows
from test_f05_history import READY, initial
from test_prompt_enrichment_http import _message


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("decision", ["SELECT_OPTION", "ACCEPT", "REJECT", "SKIP", "UNKNOWN"])
def test_native_answer_cannot_bypass_current_keep(engine, tmp_path, base, decision):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base, READY + " I prefer emerald cut center stone.")
        ctx.runtime.continuation_enabled = True
        admission, _ = admit(ctx)
        assert admission.status_code == 201, admission.json()
        state = admission.json()["current_state"]
        question = next(
            q["native_question"]
            for q in state["questions"]
            if q["question_kind"] == "NATIVE"
            and q["native_question"]["category"] == "preference_acceptance"
        )
        option = question["options"][0]
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic native decision."
        )
        native = dict(
            retained_base=base,
            decision=decision,
            selected_option=option["value"] if decision == "SELECT_OPTION" else None,
        )
        if base == "F":
            native["selected_option_id"] = (
                option["option_id"] if decision == "SELECT_OPTION" else None
            )
        payload = dict(
            schema_version="3.0.0",
            answer_kind="NATIVE",
            answer_id=str(uuid4()),
            message_id=message["message_id"],
            expected_head=state["current_frame"],
            clarification_plan_id=state["current_frame"]["plan_id"],
            clarification_id=question["clarification_id"],
            native=native,
        )
        before = rows(ctx)
        response = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=payload,
        )
        assert response.status_code == (409 if decision in {"SELECT_OPTION", "ACCEPT"} else 200), (
            response.json()
        )
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before[0]
        if decision in {"SELECT_OPTION", "ACCEPT"}:
            assert rows(ctx) == before
        else:
            from copy import deepcopy

            from jewelai_domain.preservation import contract_hash
            from pydantic import TypeAdapter, ValidationError

            from jewelai_api.continuation_results import ContinuationAnswerResult

            payload3 = deepcopy(
                ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[-1].result_payload
            )
            payload3["reason"] = "keep_release_authorized"
            payload3["content_hash"] = contract_hash(
                "jewelai.AnswerResult/3.0.0",
                {k: v for k, v in payload3.items() if k != "content_hash"},
            )
            with pytest.raises(ValidationError):
                TypeAdapter(ContinuationAnswerResult).validate_python(payload3)
            with restart(ctx, engine):
                ctx.runtime.continuation_enabled = True
                result = ctx.client.get(
                    f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                    headers=ctx.headers,
                )
                assert result.status_code == 200, result.json()
                assert result.json() == response.json()["current_state"]


@pytest.mark.parametrize("base", ["L", "F"])
def test_unrelated_native_preference_can_still_be_accepted(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base, READY + " I prefer yellow metal.")
        ctx.runtime.continuation_enabled = True
        admission, _ = admit(ctx)
        assert admission.status_code == 201, admission.json()
        state = admission.json()["current_state"]
        question = next(
            q["native_question"]
            for q in state["questions"]
            if q["question_kind"] == "NATIVE"
            and q["native_question"]["category"] == "preference_acceptance"
        )
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic preference acceptance."
        )
        native = dict(retained_base=base, decision="ACCEPT", selected_option=None)
        if base == "F":
            native["selected_option_id"] = None
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        r = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                answer_kind="NATIVE",
                answer_id=str(uuid4()),
                message_id=message["message_id"],
                expected_head=state["current_frame"],
                clarification_plan_id=state["current_frame"]["plan_id"],
                clarification_id=question["clarification_id"],
                native=native,
            ),
        )
        assert r.status_code == 200, r.json()
        after = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert after.design.metal.color.value == "yellow"
        assert after.design.center_stone == before.design.center_stone
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            result = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert result.status_code == 200, result.json()
            assert result.json() == r.json()["current_state"]


def test_native_f_explicit_resume_preserves_dormancy_gate_and_plan3(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F", READY + " I prefer yellow metal.")
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        current = a.json()["current_state"]
        q = next(
            q["native_question"]
            for q in current["questions"]
            if q["question_kind"] == "NATIVE"
            and q["native_question"]["category"] == "preference_acceptance"
        )
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit SKIP.")
        r = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                answer_kind="NATIVE",
                answer_id=str(uuid4()),
                message_id=msg["message_id"],
                expected_head=current["current_frame"],
                clarification_plan_id=current["current_frame"]["plan_id"],
                clarification_id=q["clarification_id"],
                native=dict(
                    retained_base="F",
                    decision="SKIP",
                    selected_option=None,
                    selected_option_id=None,
                ),
            ),
        )
        assert r.status_code == 200, r.json()
        current = r.json()["current_state"]
        cause = next(
            c
            for c in current["native_frontier"]["frontier_core"]["cause_states"]
            if c["cause_id"] == q["cause_id"]
        )
        assert cause["status"] == "OPEN" and cause["offer_state"] == "DORMANT"
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit native resume.")
        payload = dict(
            schema_version="3.0.0",
            resume_kind="NATIVE",
            retained_base="F",
            cause_id=q["cause_id"],
            request_id=str(uuid4()),
            message_id=msg["message_id"],
            expected_head=current["current_frame"],
        )
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarifications/{q['cause_id']}/resume"
        r = ctx.client.post(path, headers=ctx.headers, json=payload)
        assert r.status_code == 200, r.json()
        current = r.json()["current_state"]
        reoffered = next(
            x["native_question"]
            for x in current["questions"]
            if x["question_kind"] == "NATIVE" and x["native_question"]["cause_id"] == q["cause_id"]
        )
        assert reoffered["offer_trigger"] == "explicit_resume"
        assert reoffered["offer_ordinal"] == q["offer_ordinal"] + 1
        assert reoffered["clarification_id"] != q["clarification_id"]
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            result = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert result.status_code == 200, result.json()
            assert result.json() == current


def test_native_f_material_choice_uses_exact_offered_id_and_leaves_center_keep(engine, tmp_path):
    from test_f04_http import READY_TEXT
    from test_f05_admission import rows

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F", READY_TEXT + " Keep the center stone unchanged.")
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        assert a.status_code == 201, a.json()
        current = a.json()["current_state"]
        q = next(
            q["native_question"]
            for q in current["questions"]
            if q["question_kind"] == "NATIVE"
            and q["native_question"]["semantic_question_id"] == "METAL_MATERIAL"
        )
        option = next(o for o in q["options"] if o["value"] == "gold")
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic material selection."
        )
        payload = dict(
            schema_version="3.0.0",
            answer_kind="NATIVE",
            answer_id=str(uuid4()),
            message_id=message["message_id"],
            expected_head=current["current_frame"],
            clarification_plan_id=current["current_frame"]["plan_id"],
            clarification_id=q["clarification_id"],
            native=dict(
                retained_base="F",
                decision="SELECT_OPTION",
                selected_option="gold",
                selected_option_id=option["option_id"],
            ),
        )
        bad = {
            **payload,
            "native": {**payload["native"], "selected_option_id": "option_" + "0" * 64},
        }
        before = rows(ctx)
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers"
        r = ctx.client.post(path, headers=ctx.headers, json=bad)
        assert r.status_code == 422, r.json()
        assert rows(ctx) == before
        r = ctx.client.post(path, headers=ctx.headers, json=payload)
        assert r.status_code == 200, r.json()
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material.value == "gold"
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone
            == before[0].design.center_stone
        )
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            read = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert read.status_code == 200, read.json()
            assert read.json() == r.json()["current_state"]
