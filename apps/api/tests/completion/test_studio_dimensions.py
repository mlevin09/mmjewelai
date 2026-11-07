"""Studio's actual text/decision wire format through persisted HTTP; no providers."""

import pytest
from test_conversation import correct, read
from test_f04_http import answer_question, f04_session, restart, resume
from test_f05_history import initial
from test_preprod_no_defaults import preprod_enabled as preprod_enabled
from test_prompt_completion import command


@pytest.mark.parametrize("locale", ["en", "ru"])
@pytest.mark.parametrize("decision", ["SKIP", "UNKNOWN"])
def test_studio_dimension_decision_resume_and_explicit_measurements(
    engine, tmp_path, preprod_enabled, locale, decision, record_property
):
    with f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, "F", "A white gold ring with an oval diamond center stone in prong setting.")
        state = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        ).json()
        q = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_DIMENSIONS"
        )
        before = read(ctx)["revision"]["design"]
        answered = answer_question(ctx, state, q, decision)
        assert answered.status_code == 200, answered.json()
        assert read(ctx)["revision"]["design"] == before
        saved = ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[-1].result_payload
        assert saved["decision"] == decision
        reopened, _ = resume(ctx, answered.json()["state"], q["cause_id"])
        assert reopened.status_code == 200, reopened.json()
        wording = next(
            q["text"]
            for q in reopened.json()["state"]["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_DIMENSIONS"
        )
        old_text = (
            "Длина: 8 mm; Ширина: 6 mm; Глубина: 4 mm"
            if locale == "ru"
            else "Length: 8 mm; Width: 6 mm; Depth: 4 mm"
        )
        old = correct(ctx, read(ctx), f"{wording}: {old_text}")
        assert not old["revision"]["design"]["center_stone"]["dimensions"]
        text = "Центральный камень 8 x 6 x 4 мм" if locale == "ru" else "Center stone 8 x 6 x 4 mm"
        after = correct(ctx, old, f"{wording}: {text}")
        design = after["revision"]["design"]
        dimensions = design["center_stone"]["dimensions"]
        assert [dimensions["value"][axis] for axis in ["length", "width", "depth"]] == [
            {"value": v, "unit": "mm"} for v in [8, 6, 4]
        ]
        assert dimensions["origin"] == "explicit"
        assert design["metal"] == before["metal"]
        assert design["side_stones"] == before["side_stones"]
        _, final = command(ctx, after)
        assert final.status_code == 200, final.json()
        prompt = final.json()["final_prompt"]
        assert prompt["schema_version"] == "6.0.0" and not prompt["assumptions"]
        assert prompt["canonical_revision"]["design"] == design
        assert "center_stone.dimensions" not in prompt["omitted_targets"]
        with restart(ctx, engine):
            assert read(ctx)["revision"]["design"] == design
        record_property("decision", decision)
        record_property("ifp6", prompt["prompt_text"])
        assert ctx.provider.calls == []
