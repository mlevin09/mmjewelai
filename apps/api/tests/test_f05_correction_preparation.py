"""Actual source/proposal evidence before the version3 transactional writer."""

from uuid import UUID, uuid4

import pytest
from jewelai_domain.preservation import target_state
from test_f04_http import f04_session
from test_f05_admission import admit, rows
from test_f05_history import initial
from test_prompt_enrichment_http import _message

from jewelai_api.clarification_f05 import ContinuationCorrectionRequest
from jewelai_api.continuation_corrections import prepare_correction
from jewelai_api.continuation_runtime import admitted_view


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize(
    "text,outcome",
    [
        ("Emerald cut center stone.", "AWAITING_KEEP_RELEASE"),
        ("Изумрудная огранка центрального камня.", "AWAITING_KEEP_RELEASE"),
        ("Emerald cut центрального камня.", "AWAITING_KEEP_RELEASE"),
        ("Emerald cut center stone. A platinum ring.", "DEFERRED"),
        ("Maybe emerald cut center stone.", "DEFERRED"),
        ("An oval diamond center stone.", "NO_CHANGE"),
    ],
)
def test_current_source_proposal_does_not_authorize_protected_change(
    engine, tmp_path, base, text, outcome
):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
        before = rows(ctx)
        with ctx.repo.read_enrichment_history(ctx.sid, ctx.org) as repo:
            native, plan, _ = admitted_view(ctx.runtime, repo, ctx.sid, ctx.org)
            request = ContinuationCorrectionRequest(
                schema_version="3.0.0",
                request_id=uuid4(),
                message_id=UUID(msg["message_id"]),
                expected_head=native.frame,
            )
            prepared, offers = prepare_correction(
                ctx.runtime,
                repo,
                native,
                plan,
                request,
                record_id=uuid4(),
                cycle_id=uuid4(),
                plan_id=uuid4(),
                created_at=ctx.runtime._clock(),
            )
        assert prepared.outcome == outcome
        assert prepared.new_revision_id is None
        assert prepared.authoritative_revision == before[0]
        assert (
            target_state(prepared.authoritative_revision.design, "center_stone.shape").value
            == "oval"
        )
        assert rows(ctx) == before
        if outcome == "AWAITING_KEEP_RELEASE":
            assert len(offers) == len(prepared.keep_intents) == 1
            intent = prepared.keep_intents[0]
            assert intent.target.concrete_target == "center_stone.shape"
            assert intent.requested_state.value == "emerald_cut"
            assert intent.source == prepared.source
            assert (
                prepared.next_enrichment_result.protection_projection.pending_requests[
                    0
                ].current_offer_ref.id
                == offers[0].offer_id
            )
        else:
            assert not prepared.keep_intents and not offers
