"""Persisted typed consent, one-field provenance, duplicate CAS and restart."""

from uuid import UUID, uuid4

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
        from jewelai_api.continuation_plan import ContinuationPlan
        from jewelai_api.continuation_results import derive_resume_result

        plan = ContinuationPlan.model_validate(
            ctx.repo.get_clarification_plan_for_cycle(
                ctx.sid,
                UUID(result.json()["current_state"]["current_frame"]["enrichment_cycle_id"]),
                ctx.org,
            ).plan_payload
        )
        derived = derive_resume_result(plan)
        assert result.json()["committed_result_hash"] == derived.content_hash
        assert derived.content_hash != plan.content_hash
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
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        state = correct3(ctx, state, "Emerald cut center stone.")
        state = answer3(
            ctx,
            state,
            next(q["offer"] for q in state["questions"] if q["question_kind"] == "KEEP_RELEASE"),
            "ACCEPT",
        )
        state = correct3(ctx, state, "Keep the center stone unchanged.")
        assert len(state["protection_projection"]["roots"]) == 3
        state = correct3(ctx, state, "Oval center stone.")
        offer = next(q["offer"] for q in state["questions"] if q["question_kind"] == "KEEP_RELEASE")
        assert len(offer["binding"]["applicable_keep_roots"]) == 3
        state = answer3(ctx, state, offer, "ACCEPT")
        after = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert after.design.center_stone.shape.value == "oval"
        for field in type(before.design.center_stone).model_fields:
            if field != "shape":
                assert getattr(before.design.center_stone, field) == getattr(
                    after.design.center_stone, field
                )
        assert (
            len(
                {
                    a["baseline_state_sha256"]
                    for a in state["protection_projection"]["anchors"]
                    if a["target"]["concrete_target"] == "center_stone.shape"
                }
            )
            == 1
        )
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


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize(
    "availability",
    ["missing", "required", "optional", "undetermined", "not_applicable", "explicit"],
)
def test_schema11_all_additive_wrappers_survive_actual_release(
    engine, tmp_path, base, availability
):

    from jewelai_domain.models import MessageSource
    from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1
    from jewelai_domain.revisions import revise_design
    from test_f05_preview import state

    with f04_session(engine, tmp_path) as ctx:
        if base == "L":
            ctx.sid = UUID(ctx.legacy["session_id"])
        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(
            ctx.client,
            str(ctx.sid),
            str(ctx.org),
            "Explicit synthetic schema/state fixture; not professional Knowledge.",
        )
        source = MessageSource(message_id=msg["message_id"], recorded_at=old.created_at)
        migrated = migrate_design_revision_v1_to_v1_1(
            old,
            revision_id=uuid4(),
            created_at=old.created_at,
            source=source,
            reason="Explicit synthetic schema fixture",
        )
        ctx.repo.upgrade_design_session_schema_v1_1(ctx.sid, ctx.org, old.revision_id, migrated)
        extra = (
            "variety_or_type",
            "material_origin_status",
            "geographic_origin",
            "treatment_status",
            "treatments",
            "cut_style_class",
        )
        data = migrated.design.model_dump(mode="json")
        for field in extra:
            if availability == "missing":
                value = None
            elif availability in {"required", "optional", "undetermined"}:
                value = dict(availability="unknown", requirement=availability)
            elif availability == "not_applicable":
                value = dict(
                    availability="not_applicable",
                    reason="Explicit synthetic applicability fixture",
                    source=source.model_dump(mode="json"),
                )
            else:
                value = dict(
                    availability="value",
                    origin="explicit",
                    value=["synthetic_fixture"] if field == "treatments" else "synthetic_fixture",
                    source=source.model_dump(mode="json"),
                    confirmed=False,
                    locked=False,
                )
            data["center_stone"][field] = value
        if availability != "missing":
            seeded = revise_design(
                migrated,
                data,
                expected_revision_id=migrated.revision_id,
                source=source,
                reason="Explicit synthetic canonical extra wrappers",
                created_at=migrated.created_at,
            )
            ctx.repo.append_revision_cas(ctx.sid, ctx.org, migrated.revision_id, seeded)
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        current = correct3(ctx, response.json()["current_state"], "Emerald cut center stone.")
        offer = next(
            q["offer"] for q in current["questions"] if q["question_kind"] == "KEEP_RELEASE"
        )
        current = answer3(ctx, current, offer, "ACCEPT")
        after = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert after.design.center_stone.shape.value == "emerald_cut"
        assert len(current["protection_projection"]["anchors"]) == 14
        for field in type(before.design.center_stone).model_fields:
            if field != "shape":
                assert getattr(after.design.center_stone, field) == getattr(
                    before.design.center_stone, field
                )
        with restart(ctx, engine):
            assert state(ctx)["current_frame"] == current["current_frame"]
            assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == after


@pytest.mark.parametrize("base", ["L", "F"])
def test_multiple_delta_batch_is_not_partially_committed(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        assert a.status_code == 201, a.json()
        before = rows(ctx)
        current = correct3(
            ctx, a.json()["current_state"], "A platinum ring and an emerald cut center stone."
        )
        result = ctx.repo.list_user_corrections(ctx.sid, ctx.org)[-1].result_payload
        assert result["outcome"] == "DEFERRED"
        assert result["reason"] == "multiple_delta_release_unsupported"
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before[0]
        assert result["new_revision_id"] is None and result["keep_intents"] == []
        targets = {u["concrete_target"] for u in result["native_proposal"]["accepted_updates"]}
        assert {"metal.material", "center_stone.shape"}.issubset(targets)
        assert len(rows(ctx)[1]) == len(before[1]) + 1
        assert len(rows(ctx)[2]) == len(before[2]) + 1
        current = correct3(ctx, current, "A platinum ring.")
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material.value
            == "platinum"
        )
        current = correct3(ctx, current, "Emerald cut center stone.")
        assert current["status"] == "awaiting_keep_release"
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "oval"
        )
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            read = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert read.status_code == 200, read.json()
            assert read.json() == current
