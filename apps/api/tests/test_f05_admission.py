"""Actual persisted F05 admission over retained L/F histories."""

from uuid import uuid4

import pytest
from test_f04_http import f04_session, restart
from test_f05_history import initial
from test_prompt_enrichment_http import _message


def admit(ctx, *, payload=None):
    preview = ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
        headers=ctx.headers,
    )
    assert preview.status_code == 200, preview.json()
    if payload is None:
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic continuation admission."
        )
        payload = dict(
            schema_version="1.0.0",
            request_id=str(uuid4()),
            message_id=message["message_id"],
            expected_head=preview.json()["current_frame"],
        )
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/continuation-admissions",
        headers=ctx.headers,
        json=payload,
    )
    return response, payload


@pytest.mark.parametrize("base", ["L", "F"])
def test_admission_persists_cycle_plan3_and_replays_on_restart(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        response, payload = admit(ctx)
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["schema_version"] == "3.0.0" and body["command_kind"] == "ADMISSION"
        assert body["current_state"]["continuation_enabled"] is True
        assert body["current_state"]["retained_base"] == base
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
        assert (
            ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1].result.enrichment_version
            == "3.0.0"
        )
        assert (
            ctx.repo.get_clarification_plan_for_cycle(
                ctx.sid,
                ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1].enrichment_cycle_id,
                ctx.org,
            ).plan_payload["plan_version"]
            == "3.0.0"
        )
        retry, _ = admit(ctx, payload=payload)
        assert retry.status_code == 201, retry.json()
        assert retry.json()["replayed"] is True
        assert retry.json()["committed_frame"] == body["committed_frame"]
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            state = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
            assert state.status_code == 200, state.json()
            assert state.json() == body["current_state"]


def rows(ctx):
    return (
        ctx.repo.get_current_revision(ctx.sid, ctx.org),
        ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org),
        ctx.repo.list_clarification_plans(ctx.sid, ctx.org),
        ctx.repo.list_clarification_answers(ctx.sid, ctx.org),
        ctx.repo.list_user_corrections(ctx.sid, ctx.org),
    )


@pytest.mark.parametrize("base", ["L", "F"])
def test_admission_capability_stale_identity_and_source_scope(engine, tmp_path, base):
    from copy import deepcopy

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        before = rows(ctx)
        disabled, payload = admit(ctx)
        assert disabled.status_code == 409, disabled.json()
        assert disabled.json()["error"] == "continuation_unavailable"
        assert rows(ctx) == before
        ctx.runtime.continuation_enabled = True
        stale = deepcopy(payload)
        stale["expected_head"]["history_root_sha256"] = "0" * 64
        rejected, _ = admit(ctx, payload=stale)
        assert rejected.status_code == 409, rejected.json()
        assert rows(ctx) == before
        foreign = deepcopy(payload)
        foreign["message_id"] = str(uuid4())
        missing, _ = admit(ctx, payload=foreign)
        assert missing.status_code == 404, missing.json()
        assert rows(ctx) == before
        ok, _ = admit(ctx, payload=payload)
        assert ok.status_code == 201, ok.json()
        committed = rows(ctx)
        collision = deepcopy(payload)
        collision["expected_head"] = ok.json()["current_state"]["current_frame"]
        bad, _ = admit(ctx, payload=collision)
        assert bad.status_code == 409 and bad.json()["error"] == "clarification_conflict"
        assert rows(ctx) == committed
        again, _ = admit(ctx)
        assert again.status_code == 409 and again.json()["error"] == "already_admitted"
        assert rows(ctx) == committed
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            retry, _ = admit(ctx, payload=payload)
            assert retry.status_code == 201 and retry.json()["replayed"] is True
            assert retry.json()["committed_frame"] == ok.json()["committed_frame"]
            assert rows(ctx) == committed


@pytest.mark.parametrize("base", ["L", "F"])
def test_admission_output_and_plan_failure_roll_back_entire_unit(engine, tmp_path, base):
    from sqlalchemy import event

    from jewelai_api import continuation_preview

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        before = rows(ctx)

        def fail_plan(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("INSERT INTO CLARIFICATION_PLAN"):
                raise RuntimeError("Synthetic Plan3 insertion failure")

        event.listen(engine, "before_cursor_execute", fail_plan)
        try:
            response, _ = admit(ctx)
        finally:
            event.remove(engine, "before_cursor_execute", fail_plan)
        assert response.status_code == 500
        assert rows(ctx) == before
        original = continuation_preview.read_preview

        def fail_output(*args, **kwargs):
            if kwargs.get("_repository") is not None:
                raise continuation_preview.ContinuationReadError(
                    422, "artifact_capacity_exceeded", "Synthetic capacity failure"
                )
            return original(*args, **kwargs)

        # Only synthetic capacity fault; no production logger or exception behavior changes.
        continuation_preview.read_preview = fail_output
        try:
            response, _ = admit(ctx)
        finally:
            continuation_preview.read_preview = original
        assert (
            response.status_code == 422 and response.json()["error"] == "artifact_capacity_exceeded"
        )
        assert rows(ctx) == before


@pytest.mark.parametrize("base", ["L", "F"])
def test_admitted_current_outputs_are_read_only_and_old_reads_are_explicitly_refused(
    engine, tmp_path, base
):
    from sqlalchemy import event
    from test_f05_preview import output, state

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        expected = response.json()["current_state"]
        before = rows(ctx)
        statements = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            assert state(ctx) == expected
            final = output(ctx, expected, projection=base == "L")
            assert final.status_code == 200, final.json()
            ifp = final.json()["internal_final_prompt"]
            assert ifp["current_frame"] == expected["current_frame"]
            assert ifp["artifact_versions"]["enrichment_version"] == "3.0.0"
            assert ifp["protection_projection"] == expected["protection_projection"]
            if base == "F":
                assert ifp["native_frontier"]["current_plan_ref"] == dict(
                    plan_id=expected["current_frame"]["plan_id"],
                    content_hash=expected["current_frame"]["plan_hash"],
                )
            for endpoint in ("state", "final-output"):
                old = ctx.client.get(
                    f"/v1/sessions/{ctx.sid}/prompt-enrichment/{endpoint}", headers=ctx.headers
                )
                assert (
                    old.status_code == 409 and old.json()["error"] == "unsupported_workflow_version"
                )
            with restart(ctx, engine):
                assert state(ctx)["current_frame"] == expected["current_frame"]
                assert output(ctx, expected, projection=base == "L").json() == final.json()
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}
        assert rows(ctx) == before
        assert ctx.provider.calls == []


@pytest.mark.parametrize("base", ["L", "F"])
def test_rehashed_admission_source_tampering_is_not_trusted(engine, tmp_path, base):
    from copy import deepcopy

    from jewelai_domain.preservation import contract_hash
    from jewelai_persistence.models import ClarificationPlanRow
    from sqlalchemy import update

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        plan_id = response.json()["committed_frame"]["plan_id"]
        from uuid import UUID

        record = ctx.repo.get_clarification_plan(ctx.sid, UUID(plan_id), ctx.org)
        bad = deepcopy(record.plan_payload)
        bad["trigger"]["source_message_sha256"] = "0" * 64
        bad["content_hash"] = contract_hash(
            "jewelai.ClarificationPlan/3.0.0", {k: v for k, v in bad.items() if k != "content_hash"}
        )
        with ctx.repo._session_factory.begin() as db:
            db.execute(
                update(ClarificationPlanRow)
                .where(ClarificationPlanRow.clarification_plan_id == UUID(plan_id))
                .values(plan_payload=bad, content_hash=bad["content_hash"])
            )
        broken = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
            headers=ctx.headers,
        )
        assert broken.status_code == 500 and broken.json()["error"] == "invalid_durable_history"


@pytest.mark.parametrize("base", ["L", "F"])
def test_admission_does_not_allow_frozen_native_writers_to_append(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        old = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        ).json()
        source = _message(ctx.client, str(ctx.sid), str(ctx.org), "A platinum ring.")
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        before = rows(ctx)
        correction = dict(
            expected_revision_id=old["authoritative_revision_id"], message_id=source["message_id"]
        )
        answer = dict(
            clarification_plan_id=old["clarification_plan_id"],
            clarification_id="synthetic-old-question",
            decision="SKIP",
            selected_option=None,
            expected_revision_id=old["authoritative_revision_id"],
            answer_id=str(uuid4()),
            message_id=source["message_id"],
        )
        if base == "F":
            correction.update(
                schema_version="2.0.0",
                expected_enrichment_cycle_id=old["enrichment_cycle_id"],
                expected_enrichment_result_hash=before[1][-2].result.content_hash,
                expected_clarification_plan_hash=old["clarification_plan_content_hash"],
            )
            answer.update(
                schema_version="2.0.0",
                plan_content_hash=old["clarification_plan_content_hash"],
                selected_option_id=None,
            )
        for endpoint, payload in (("corrections", correction), ("clarification-answers", answer)):
            blocked = ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/{endpoint}",
                headers=ctx.headers,
                json=payload,
            )
            assert blocked.status_code == 409, blocked.json()
            assert blocked.json()["error"] == "unsupported_workflow_version"
            assert rows(ctx) == before


@pytest.mark.parametrize("base", ["L", "F"])
def test_membership_rechecked_after_http_authorization_before_admission_commit(
    engine, tmp_path, base, monkeypatch
):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        member_headers = {**ctx.headers, "Authorization": "Bearer test-f05-revoked"}
        member = ctx.client.get("/me", headers=member_headers).json()
        membership = f"/organizations/{ctx.org}/memberships"
        added = ctx.client.post(
            membership, json={"principal_id": member["principal_id"], "role": "member"}
        )
        assert added.status_code == 201, added.json()
        ctx.runtime.continuation_enabled = True
        before = rows(ctx)
        commit = ctx.repo.commit_continuation

        def revoke_then_commit(*args, **kwargs):
            removed = ctx.client.delete(f"{membership}/{member['principal_id']}")
            assert removed.status_code == 204
            return commit(*args, **kwargs)

        monkeypatch.setattr(ctx.repo, "commit_continuation", revoke_then_commit)
        ctx.headers = member_headers
        response, _ = admit(ctx)
        assert response.status_code == 404, response.json()
        assert rows(ctx) == before


@pytest.mark.parametrize("base", ["L", "F"])
def test_schema11_admission_retains_all_fourteen_wrappers_and_disabled_readback(
    engine, tmp_path, base
):
    from uuid import UUID

    from jewelai_domain.models import MessageSource
    from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1
    from test_f05_preview import output, state

    with f04_session(engine, tmp_path) as ctx:
        if base == "L":
            ctx.sid = UUID(ctx.legacy["session_id"])
        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Synthetic schema1.1 fixture.")
        migrated = migrate_design_revision_v1_to_v1_1(
            old,
            revision_id=uuid4(),
            created_at=old.created_at,
            source=MessageSource(message_id=msg["message_id"], recorded_at=old.created_at),
            reason="Explicit synthetic schema1.1 fixture",
        )
        ctx.repo.upgrade_design_session_schema_v1_1(ctx.sid, ctx.org, old.revision_id, migrated)
        initial(ctx, base)
        before = rows(ctx)
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        current = response.json()["current_state"]
        assert len(current["protection_projection"]["anchors"]) == 14
        assert before[0] == ctx.repo.get_current_revision(ctx.sid, ctx.org)
        with restart(ctx, engine):
            read = state(ctx)
            assert read["continuation_enabled"] is False
            assert read["current_frame"] == current["current_frame"]
            final = output(ctx, read, projection=base == "L")
            assert final.status_code == 200, final.json()


def test_cycle3_codec_checks_actual_native_context_not_only_rehashed_outer_metadata(
    engine, tmp_path
):
    from copy import deepcopy

    from jewelai_domain.preservation import contract_hash
    from jewelai_prompts.continuation import ContinuationEnrichmentResult
    from pydantic import ValidationError

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F")
        ctx.runtime.continuation_enabled = True
        admitted, _ = admit(ctx)
        assert admitted.status_code == 201, admitted.json()
        valid = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1].result.model_dump(mode="json")
        for kind in ("native_pins", "interpreter"):
            bad = deepcopy(valid)
            if kind == "native_pins":
                bad["context"]["artifact_pins"]["role_artifact_version"] = "99.0.0"
            else:
                bad["context"]["parser_interpreter_id"] = "legacy-bc34-1.1"
            bad["content_hash"] = contract_hash(
                "jewelai.CycleResult/3.0.0", {k: v for k, v in bad.items() if k != "content_hash"}
            )
            with pytest.raises(ValidationError):
                ContinuationEnrichmentResult.model_validate(bad)
