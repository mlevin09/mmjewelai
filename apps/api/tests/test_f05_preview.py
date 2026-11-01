"""F05 negotiated current outputs use real native HTTP and zero-write reads."""

from uuid import uuid4

import pytest
from jewelai_domain.preservation import contract_hash
from jewelai_prompts.downstream_preparation import (
    GenerationPreparationError,
    build_generation_preparation,
    decode_canonical_handoff,
    decode_canonical_internal_final_prompt,
    render_semantic_source,
)
from jewelai_prompts.downstream_preparation_v2 import (
    build_generation_preparation_v2,
    render_semantic_source_v2,
)
from jewelai_prompts.final_prompt_v4 import CanonicalInternalFinalPromptV4
from jewelai_prompts.handoff import build_internal_final_prompt_handoff
from pydantic import ValidationError
from sqlalchemy import event
from test_f04_http import f04_session, restart
from test_f05_compatibility import correction
from test_f05_history import initial
from test_prompt_enrichment_http import _message


def state(ctx):
    response = ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
        headers=ctx.headers,
    )
    assert response.status_code == 200, response.json()
    return response.json()


def output(ctx, preview, *, projection=True):
    return ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output?output_version=4.0.0"
        + ("&projection=jewelai.legacy-l.compat/1.0.0" if projection else ""),
        headers={**ctx.headers, "If-Match": preview["current_frame"]["history_root_sha256"]},
    )


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("locale", ["en", "ru"])
def test_negotiated_output_roundtrip_restart_no_writes_and_no_preparation(
    engine, tmp_path, base, locale
):
    with f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, base)
        first = state(ctx)
        statements = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            result = output(ctx, first, projection=base == "L")
            assert result.status_code == 200, result.json()
            source = decode_canonical_internal_final_prompt(result.json()["internal_final_prompt"])
            handoff = build_internal_final_prompt_handoff(result.json())
            assert decode_canonical_handoff(handoff.model_dump(mode="json")) == handoff
            assert source.current_frame.model_dump(mode="json") == first["current_frame"]
            assert source.artifact_versions.question_artifact_version == (
                "1.0.0" if base == "L" else "2.0.0"
            )
            roots = {r.root_ref.evidence_id for r in source.protection_projection.roots}
            keep = [
                c
                for c in source.constraints
                if c.kind == "preservation" and roots.intersection(c.source_ids)
            ]
            assert len(keep) == 1 and keep[0].target == "component.center_stone"
            for prepare in (build_generation_preparation, build_generation_preparation_v2):
                for wire in (handoff, handoff.model_dump(mode="json"), handoff.model_dump_json()):
                    with pytest.raises(GenerationPreparationError) as failure:
                        prepare(wire, {}, preparation_id=uuid4(), created_at=None)
                    assert failure.value.code.value == "unsupported_source_version"
            for render in (render_semantic_source, render_semantic_source_v2):
                with pytest.raises(GenerationPreparationError) as failure:
                    render(handoff, {})
                assert failure.value.code.value == "unsupported_source_version"
            for invalid in (None, "", '"' + "0" * 64 + '"', 'W/"' + "0" * 64 + '"'):
                headers = dict(ctx.headers)
                if invalid is not None:
                    headers["If-Match"] = invalid
                bad = ctx.client.get(
                    f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output"
                    "?output_version=4.0.0"
                    + ("&projection=jewelai.legacy-l.compat/1.0.0" if base == "L" else ""),
                    headers=headers,
                )
                assert bad.status_code == (422 if invalid is None else 409), bad.json()
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert not set(statements).intersection(
            {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}
        )
        with restart(ctx, engine):
            assert state(ctx) == first
            assert output(ctx, first, projection=base == "L").json() == result.json()
        assert ctx.provider.calls == []


def test_orphan_message_does_not_stale_but_correction_does(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "L")
        before = state(ctx)
        _message(ctx.client, str(ctx.sid), str(ctx.org), "Unprocessed synthetic request.")
        assert state(ctx) == before
        assert output(ctx, before).status_code == 200
        correction(ctx, "A platinum ring.")
        assert state(ctx)["current_frame"] != before["current_frame"]
        assert output(ctx, before).status_code == 409


def test_rehashed_ifp_cannot_change_frame_or_cross_scope(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "L")
        result = output(ctx, state(ctx))
        assert result.status_code == 200, result.json()
        source = result.json()["internal_final_prompt"]
        for field in ("session_id", "product_state_revision_id", "enrichment_cycle_id"):
            bad = {**source, field: str(uuid4())}
            bad["content_hash"] = contract_hash(
                "jewelai.InternalFinalPrompt/4.0.0",
                {k: v for k, v in bad.items() if k != "content_hash"},
            )
            with pytest.raises(ValidationError):
                CanonicalInternalFinalPromptV4.model_validate(bad)
        missing = dict(source)
        del missing["schema_version"]
        with pytest.raises(GenerationPreparationError):
            decode_canonical_internal_final_prompt(missing)


def test_preview_preserves_organization_scope_and_rejects_wrong_projection(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "L")
        current = state(ctx)
        wrong = output(ctx, current, projection=False)
        assert wrong.status_code == 422 and wrong.json()["error"] == "invalid_projection"
        other = ctx.client.post("/organizations", json={"name": "Separate synthetic organization"})
        assert other.status_code == 201, other.json()
        response = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
            headers={"X-Organization-ID": other.json()["organization_id"]},
        )
        assert response.status_code == 404
        assert state(ctx) == current


def test_context_projection_does_not_suppress_independent_request(engine, tmp_path):
    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "L")
        correction(ctx, "White metal. Maybe rose gold.")
        current = state(ctx)
        assert current["compatibility_projection"]["remaining_blocker_refs"]
        blocked = output(ctx, current)
        assert blocked.status_code == 409 and blocked.json()["error"] == "final_output_blocked"


def test_legacy_applied_native_answer_replays_actual_message_and_revision(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        initial(
            ctx,
            "L",
            "A white or yellow gold ring with an oval diamond center stone in prong setting. "
            "Center stone 8 x 6 x 4 mm.",
        )
        native = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        ).json()
        question = next(
            q
            for q in native["clarification_questions"]
            if q["semantic_question_id"] == "METAL_COLOR"
        )
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic oval answer."
        )
        answer = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=dict(
                clarification_plan_id=native["clarification_plan_id"],
                clarification_id=question["clarification_id"],
                decision="SELECT_OPTION",
                selected_option=question["options"][0]["value"],
                expected_revision_id=native["authoritative_revision_id"],
                answer_id=str(uuid4()),
                message_id=message["message_id"],
            ),
        )
        assert answer.status_code == 200, answer.json()
        assert answer.json()["outcome"] == "APPLIED"
        current = state(ctx)
        result = output(ctx, current)
        assert result.status_code == 200, result.json()
        with restart(ctx, engine):
            assert state(ctx) == current
            assert output(ctx, current).json() == result.json()


def test_f_native_open_causes_stay_blocking_and_typed_in_preview(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F", "A gold ring.")
        current = state(ctx)
        frontier = current["native_frontier"]
        assert any(
            c["criticality"] == "BLOCKING" and c["status"] == "OPEN"
            for c in frontier["frontier_core"]["cause_states"]
        )
        assert current["description"]["sealed_frontier_hash"] == frontier["content_hash"]
        assert current["compatibility_projection"] is None
        assert current["continuation_enabled"] is False
        blocked = output(ctx, current, projection=False)
        assert blocked.status_code == 409 and blocked.json()["error"] == "final_output_blocked"
        with restart(ctx, engine):
            assert state(ctx) == current
