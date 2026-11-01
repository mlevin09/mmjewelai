"""Narrow compatibility proof from real native HTTP and actual immutable records."""

from uuid import UUID, uuid4

import pytest
from conftest import NOW
from jewelai_domain.models import MessageSource
from jewelai_domain.revisions import revise_design
from test_f04_http import f04_session
from test_f05_history import frame, initial
from test_prompt_enrichment_http import _message

from jewelai_api.compatibility_projection import project_legacy_readiness
from jewelai_api.continuation_preview import read_preview


def correction(ctx, text):
    old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    result = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
        headers=ctx.headers,
        json=dict(expected_revision_id=str(old.revision_id), message_id=message["message_id"]),
    )
    assert result.status_code == 200, result.json()
    return result.json()["state"]


def projection(ctx):
    with ctx.repo.read_enrichment_history(ctx.sid, ctx.org) as reader:
        return project_legacy_readiness(ctx.runtime, reader, frame(ctx), ctx.sid, ctx.org)


@pytest.mark.parametrize("language", ["EN", "RU", "MIXED"])
def test_required_unknown_is_discharged_only_by_actual_same_target_correction(
    engine, tmp_path, language
):
    with f04_session(engine, tmp_path) as ctx:
        ctx.sid = UUID(ctx.legacy["session_id"])
        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic unknown dimensions."
        )
        source = MessageSource(message_id=msg["message_id"], recorded_at=NOW)
        design = old.design.model_dump(mode="json")
        design["center_stone"]["dimensions"] = dict(availability="unknown", requirement="required")
        seeded = revise_design(
            old,
            design,
            expected_revision_id=old.revision_id,
            source=source,
            reason="Synthetic required unknown fixture",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, old.revision_id, seeded)
        initial(ctx, "L", "A white gold ring with an oval diamond center stone in prong setting.")
        state = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        ).json()
        question = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_DIMENSIONS"
        )
        answer_message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic UNKNOWN answer."
        )
        answer = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=dict(
                clarification_plan_id=state["clarification_plan_id"],
                clarification_id=question["clarification_id"],
                decision="UNKNOWN",
                selected_option=None,
                expected_revision_id=state["authoritative_revision_id"],
                answer_id=str(uuid4()),
                message_id=answer_message["message_id"],
            ),
        )
        assert answer.status_code == 200, answer.json()
        original = ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0].result_payload
        correction(ctx, "A platinum ring.")
        unrelated = projection(ctx)
        assert not unrelated.proofs and unrelated.remaining_blocker_refs
        correction(
            ctx,
            {
                "EN": "Center stone 8 x 6 x 4 mm.",
                "RU": "Центральный камень 8 x 6 x 4 мм.",
                "MIXED": "Центральный камень 8 x 6 x 4 mm.",
            }[language],
        )
        actual = projection(ctx)
        assert len(actual.proofs) == 1 and not actual.remaining_blocker_refs
        assert actual.proofs[0].target.concrete_target == "center_stone.dimensions"
        assert ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0].result_payload == original
        assert original["blocks_progression"] is True
        old_final = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert old_final.status_code == 409  # Frozen reader still means exactly the same thing.
        bootstrap = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
            headers=ctx.headers,
        )
        assert bootstrap.status_code == 200, bootstrap.json()
        current = bootstrap.json()["current_frame"]
        repaired = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output"
            "?output_version=4.0.0&projection=jewelai.legacy-l.compat/1.0.0",
            headers={**ctx.headers, "If-Match": current["history_root_sha256"]},
        )
        assert repaired.status_code == 200, repaired.json()
        prompt = repaired.json()["internal_final_prompt"]
        assert prompt["schema_version"] == "4.0.0"
        assert prompt["current_frame"] == current
        assert prompt["product_state_revision_id"] == current["revision_id"]
        assert not any(d["blocking"] for d in prompt["unresolved_details"])
        historical = next(d for d in prompt["decision_lineage"] if d["outcome"] == "UNKNOWN")
        assert historical["blocks_progression"] is True
        assert not prompt["compatibility_projection"]["remaining_blocker_refs"]
        assert ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0].result_payload == original
        # The new output is derived, never persisted or selected as the native source.
        assert read_preview(ctx.runtime, ctx.sid, ctx.org).continuation_enabled is False


@pytest.mark.parametrize(
    "locale,text,color",
    [
        ("en", "Yellow metal.", "yellow"),
        ("ru", "Желтый металл.", "yellow"),
        ("en", "White metal.", "white"),
        ("ru", "Белый металл.", "white"),
        ("en", "Yellow металл.", "yellow"),
    ],
)
@pytest.mark.parametrize("binding", [False, True])
def test_context_proof_does_not_reparse_or_promote_knowledge_to_stone_fact(
    engine, tmp_path, locale, text, color, binding
):
    with f04_session(engine, tmp_path, binding=binding, locale=locale) as ctx:
        initial(
            ctx,
            "L",
            "A white gold ring with an oval diamond center stone in prong setting. "
            "Center stone 8 x 6 x 4 mm.",
        )
        correction(ctx, text)
        records = ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        original = records[0].result_payload
        result = projection(ctx)
        assert result.proofs
        assert all(p.kind == "context_owner_token_consumed" for p in result.proofs)
        assert all(p.accepted_target.concrete_target == "metal.color" for p in result.proofs)
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.color is None
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.color.value == color
        assert ctx.repo.list_user_corrections(ctx.sid, ctx.org)[0].result_payload == original
        native = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert native.status_code in {200, 409}
        if binding and color == "white":
            assert native.status_code == 409
        preview = read_preview(ctx.runtime, ctx.sid, ctx.org)
        repaired = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output"
            "?output_version=4.0.0&projection=jewelai.legacy-l.compat/1.0.0",
            headers={**ctx.headers, "If-Match": preview.current_frame.history_root_sha256},
        )
        assert repaired.status_code == 200, repaired.json()
        assert not repaired.json()["internal_final_prompt"]["compatibility_projection"][
            "remaining_blocker_refs"
        ]
