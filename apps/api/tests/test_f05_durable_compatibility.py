"""Actual admitted UNKNOWN -> scoped consent proof, without rewriting old flags."""

from uuid import UUID, uuid4

from conftest import NOW
from jewelai_domain.models import MessageSource
from jewelai_domain.revisions import revise_design
from test_f04_http import f04_session, restart
from test_f05_admission import admit
from test_f05_history import initial
from test_f05_preview import output, state
from test_prompt_enrichment_http import _message


def test_original_unknown_requires_actual_keep_accept_to_discharge(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        ctx.sid = UUID(ctx.legacy["session_id"])
        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Synthetic required unknown fixture."
        )
        design = old.design.model_dump(mode="json")
        design["center_stone"]["dimensions"] = dict(availability="unknown", requirement="required")
        seeded = revise_design(
            old,
            design,
            expected_revision_id=old.revision_id,
            source=MessageSource(message_id=msg["message_id"], recorded_at=NOW),
            reason="Synthetic required unknown fixture",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, old.revision_id, seeded)
        initial(ctx, "L", "A white gold ring with an oval diamond center stone in prong setting.")
        native = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        ).json()
        q = next(
            q
            for q in native["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_DIMENSIONS"
        )
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit UNKNOWN.")
        result = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=dict(
                clarification_plan_id=native["clarification_plan_id"],
                clarification_id=q["clarification_id"],
                decision="UNKNOWN",
                selected_option=None,
                expected_revision_id=native["authoritative_revision_id"],
                answer_id=str(uuid4()),
                message_id=msg["message_id"],
            ),
        )
        assert result.status_code == 200, result.json()
        original = ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0].result_payload
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        assert a.status_code == 201, a.json()
        current = a.json()["current_state"]
        for text in ("Keep the center stone unchanged.", "Center stone 8 x 6 x 4 mm."):
            msg = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
            r = ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
                headers=ctx.headers,
                json=dict(
                    schema_version="3.0.0",
                    request_id=str(uuid4()),
                    message_id=msg["message_id"],
                    expected_head=current["current_frame"],
                ),
            )
            assert r.status_code == 200, r.json()
            current = r.json()["current_state"]
        assert output(ctx, current).status_code == 409
        assert (
            ctx.repo.get_current_revision(
                ctx.sid, ctx.org
            ).design.center_stone.dimensions.availability
            == "unknown"
        )
        q = next(q["offer"] for q in current["questions"] if q["question_kind"] == "KEEP_RELEASE")
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic consent.")
        r = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                answer_kind="KEEP_RELEASE",
                answer_id=str(uuid4()),
                message_id=msg["message_id"],
                expected_head=current["current_frame"],
                clarification_plan_id=current["current_frame"]["plan_id"],
                clarification_id=q["offer_id"],
                intent_id=q["intent_id"],
                requested_value_sha256=q["requested_value_sha256"],
                decision="ACCEPT",
            ),
        )
        assert r.status_code == 200, r.json()
        current = r.json()["current_state"]
        proof = next(
            p
            for p in current["compatibility_projection"]["proofs"]
            if p["kind"] == "accepted_target_replaces_unknown"
        )
        assert proof["accepted_event_ref"]["kind"] == "keep_release_answer"
        assert not current["compatibility_projection"]["remaining_blocker_refs"]
        assert ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0].result_payload == original
        assert original["blocks_progression"] is True
        final = output(ctx, current)
        assert final.status_code == 200, final.json()
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
            assert output(ctx, current).json() == final.json()
