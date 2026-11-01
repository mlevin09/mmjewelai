from uuid import uuid4

from test_f04_http import f04_session, restart
from test_f05_admission import admit
from test_f05_history import READY, initial
from test_f05_matrix import current_offer
from test_f05_preview import output
from test_f05_release_http import answer3, correct3
from test_prompt_enrichment_http import _message


def native_accept(ctx, current, q):
    m = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic native acceptance.")
    r = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
        headers=ctx.headers,
        json=dict(
            schema_version="3.0.0",
            answer_kind="NATIVE",
            answer_id=str(uuid4()),
            message_id=m["message_id"],
            expected_head=current["current_frame"],
            clarification_plan_id=current["current_frame"]["plan_id"],
            clarification_id=q["clarification_id"],
            native=dict(
                retained_base="F", decision="ACCEPT", selected_option=None, selected_option_id=None
            ),
        ),
    )
    assert r.status_code == 200, r.json()
    return r.json()["current_state"]


def test_combined_x20_dag(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F", READY + " I prefer yellow metal.")
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        current = a.json()["current_state"]
        current = correct3(ctx, current, "Emerald cut center stone.")
        current = answer3(ctx, current, current_offer(current), "ACCEPT")
        current = correct3(ctx, current, "I prefer yellow metal.")
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
        current = native_accept(ctx, current, reoffered)
        final = output(ctx, current, projection=False)
        assert final.status_code == 200, final.json()
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            result = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert result.status_code == 200, result.json()
            assert result.json() == current
            assert output(ctx, current, projection=False).json() == final.json()
