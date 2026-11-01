"""Typed scoped consent prepares exactly one canonical child; it never writes by itself."""

from uuid import UUID, uuid4

import pytest
from jewelai_domain.preservation import anchor_hash, target_state
from test_f04_http import f04_session
from test_f05_admission import admit, rows
from test_f05_history import initial
from test_prompt_enrichment_http import _message

from jewelai_api.clarification_f05 import KeepReleaseAnswerRequest
from jewelai_api.continuation_answers import prepare_answer
from jewelai_api.continuation_results import ContinuationCorrectionResult
from jewelai_api.continuation_runtime import admitted_view


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_typed_keep_decision_has_original_value_source_and_distinct_authorization(
    engine, tmp_path, base, decision
):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        message = _message(ctx.client, str(ctx.sid), str(ctx.org), "Emerald cut center stone.")
        correction = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                request_id=str(uuid4()),
                message_id=message["message_id"],
                expected_head=response.json()["current_state"]["current_frame"],
            ),
        )
        assert correction.status_code == 200, correction.json()
        current = correction.json()["current_state"]
        question = next(q for q in current["questions"] if q["question_kind"] == "KEEP_RELEASE")[
            "offer"
        ]
        consent = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic scoped decision."
        )
        request = KeepReleaseAnswerRequest(
            schema_version="3.0.0",
            answer_kind="KEEP_RELEASE",
            answer_id=uuid4(),
            message_id=UUID(consent["message_id"]),
            expected_head=current["current_frame"],
            clarification_plan_id=current["current_frame"]["plan_id"],
            clarification_id=question["offer_id"],
            intent_id=question["intent_id"],
            requested_value_sha256=question["requested_value_sha256"],
            decision=decision,
        )
        before = rows(ctx)
        with ctx.repo.read_enrichment_history(ctx.sid, ctx.org) as repo:
            native, plan, _ = admitted_view(ctx.runtime, repo, ctx.sid, ctx.org)
            records = repo.list_user_corrections(ctx.sid, ctx.org)
            result = ContinuationCorrectionResult.model_validate(records[-1].result_payload)
            intents = {i.intent_id: (i, result) for i in result.keep_intents}
            answer = prepare_answer(
                ctx.runtime,
                repo,
                native,
                plan,
                request,
                cycle_id=uuid4(),
                created_at=ctx.runtime._clock(),
                intents=intents,
            )
        assert rows(ctx) == before
        if decision == "ACCEPT":
            assert answer.outcome == "APPLIED" and answer.new_revision_id
            new = answer.resulting_revision
            assert new.design.center_stone.shape.value == "emerald_cut"
            assert new.design.center_stone.shape.source.message_id == message["message_id"]
            assert new.event.source.message_id == consent["message_id"]
            old = before[0]
            for name in type(old.design.center_stone).model_fields:
                if name != "shape":
                    assert getattr(new.design.center_stone, name) == getattr(
                        old.design.center_stone, name
                    )
            assert all(
                a.baseline_state_sha256
                == anchor_hash(target_state(new.design, a.target.concrete_target))
                for a in answer.next_enrichment_result.protection_projection.anchors
            )
            assert (
                answer.next_enrichment_result.protection_projection.applied_decision_refs[-1].id
                == request.answer_id
            )
        else:
            assert answer.outcome == "REJECTED" and answer.new_revision_id is None
            assert not answer.next_enrichment_result.protection_projection.applied_decision_refs
        assert not answer.next_enrichment_result.protection_projection.pending_requests
