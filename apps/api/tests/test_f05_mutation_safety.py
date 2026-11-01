"""Actual version3 writers fail closed and readers never repair persistent state."""

from copy import deepcopy
from uuid import uuid4

import pytest
from jewelai_domain.preservation import contract_hash
from jewelai_persistence.models import ClarificationAnswerRow
from sqlalchemy import event, update
from test_f04_http import f04_session, restart
from test_f05_admission import rows
from test_f05_preview import output, state
from test_f05_release_http import (
    answer3,
    consent_payload,
    correct3,
    correction_payload,
    pending_fixture,
)
from test_prompt_enrichment_http import _message


@pytest.mark.parametrize("base", ["L", "F"])
def test_stale_changed_identity_tenant_disabled_writer_and_read_only(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        current, offer = pending_fixture(ctx, base)
        original = consent_payload(ctx, current, offer, "ACCEPT")
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers"
        success = ctx.client.post(path, headers=ctx.headers, json=original)
        assert success.status_code == 200, success.json()
        current = success.json()["current_state"]
        current = correct3(ctx, current, "A platinum ring.")
        committed = rows(ctx)
        repeated = ctx.client.post(path, headers=ctx.headers, json=original)
        assert repeated.status_code == 200 and repeated.json()["replayed"], repeated.json()
        assert repeated.json()["committed_frame"] == success.json()["committed_frame"]
        assert repeated.json()["current_state"] == current
        assert rows(ctx) == committed
        changed = deepcopy(original)
        changed["decision"] = "REJECT"
        assert ctx.client.post(path, headers=ctx.headers, json=changed).status_code == 409
        stale = deepcopy(original)
        stale["answer_id"] = str(uuid4())
        assert ctx.client.post(path, headers=ctx.headers, json=stale).status_code == 409
        other = ctx.client.post("/organizations", json={"name": "Other synthetic organization"})
        assert other.status_code == 201
        foreign = ctx.client.post(
            path, headers={"X-Organization-ID": other.json()["organization_id"]}, json=original
        )
        assert foreign.status_code == 404, foreign.json()
        assert rows(ctx) == committed
        fresh = correction_payload(ctx, current, "A gold ring.")
        ctx.runtime.continuation_enabled = False
        disabled = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections", headers=ctx.headers, json=fresh
        )
        assert disabled.status_code == 409, disabled.json()
        duplicate = ctx.client.post(path, headers=ctx.headers, json=original)
        assert duplicate.status_code == 200 and duplicate.json()["replayed"], duplicate.json()
        assert duplicate.json()["current_state"]["continuation_enabled"] is False
        assert rows(ctx) == committed
        statements = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            saved = state(ctx)
            final = output(ctx, saved, projection=base == "L")
            assert final.status_code == 200, final.json()
            wrong = deepcopy(saved)
            wrong["current_frame"]["history_root_sha256"] = "0" * 64
            assert output(ctx, wrong, projection=base == "L").status_code == 409
            with restart(ctx, engine):
                assert state(ctx) == saved
                assert output(ctx, saved, projection=base == "L").json() == final.json()
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}


@pytest.mark.parametrize("base", ["L", "F"])
def test_new_envelope_capacity_and_malformed_request_do_not_append(
    engine, tmp_path, base, monkeypatch
):
    from jewelai_api import continuation_runtime
    from jewelai_api.continuation_preview import ContinuationReadError

    with f04_session(engine, tmp_path) as ctx:
        current, offer = pending_fixture(ctx, base)
        answer = consent_payload(ctx, current, offer, "ACCEPT")
        before = rows(ctx)

        def too_large(*artifacts):
            raise ContinuationReadError(
                422, "artifact_capacity_exceeded", "Synthetic envelope limit"
            )

        with monkeypatch.context() as m:
            m.setattr(continuation_runtime, "check_capacity", too_large)
            r = ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
                headers=ctx.headers,
                json=answer,
            )
        assert r.status_code == 422, r.json()
        assert rows(ctx) == before
        request = correction_payload(ctx, current, "x" * 2001)
        r = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json=request,
        )
        assert r.status_code == 422, r.json()
        assert rows(ctx) == before
        raw = '{"schema_version":"3.0.0","schema_version":"3.0.0","request_id":NaN}'
        r = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers={**ctx.headers, "Content-Type": "application/json"},
            content=raw,
        )
        assert r.status_code == 422, r.json()
        assert rows(ctx) == before


def test_rehashed_answer_source_corruption_fails_actual_source_replay(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        current, offer = pending_fixture(ctx, "L")
        current = answer3(ctx, current, offer, "ACCEPT")
        record = ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[-1]
        revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        payload = deepcopy(record.result_payload)
        # A local synthetic DB fault, never a legitimate user/update operation.
        payload["message_sha256"] = "0" * 64
        payload["content_hash"] = contract_hash(
            "jewelai.AnswerResult/3.0.0", {k: v for k, v in payload.items() if k != "content_hash"}
        )
        with ctx.repo._session_factory.begin() as db:
            db.execute(
                update(ClarificationAnswerRow)
                .where(ClarificationAnswerRow.answer_record_id == record.answer_record_id)
                .values(result_payload=payload, content_hash=payload["content_hash"])
            )
        r = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
            headers=ctx.headers,
        )
        assert r.status_code == 500, r.json()
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == revision


@pytest.mark.parametrize("length,expected", [(20000, 200), (20001, 422)])
def test_pending_description_exact_capacity_is_typed_and_read_only(
    engine, tmp_path, monkeypatch, length, expected
):
    from jewelai_api import continuation_planning

    with f04_session(engine, tmp_path) as ctx:
        current, _ = pending_fixture(ctx, "L")
        description = current["description"]
        old_line = description["unresolved_summary"][-1]
        assert description["text"].endswith(old_line)
        base_length = len(description["text"]) - len(old_line) - 1
        # Synthetic renderer-sized input; source/intent/row validation still runs.
        monkeypatch.setattr(
            continuation_planning,
            "pending_descriptions",
            lambda *args: ("X" * (length - base_length - 1),),
        )
        statements = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            response = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
                headers=ctx.headers,
            )
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert response.status_code == expected, response.json()
        if expected == 200:
            assert len(response.json()["description"]["text"]) == length
        else:
            assert response.json()["error"] == "artifact_capacity_exceeded"
        assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}


@pytest.mark.parametrize("base", ["L", "F"])
def test_pending_offer_cannot_be_changed_by_legacy_confirmation_or_lock_writer(
    engine, tmp_path, base
):
    with f04_session(engine, tmp_path) as ctx:
        current, _ = pending_fixture(ctx, base)
        msg = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic legacy authority attempt."
        )
        before = rows(ctx)
        source = dict(
            kind="message",
            message_id=msg["message_id"],
            recorded_at=before[0].created_at.isoformat(),
        )
        for action in ("confirm", "lock"):
            response = ctx.client.post(
                f"/sessions/{ctx.sid}/revisions",
                headers=ctx.headers,
                json=dict(
                    action=action,
                    target="center_stone.shape",
                    expected_revision_id=current["current_frame"]["revision_id"],
                    source=source,
                    reason="Synthetic legacy authority attempt",
                ),
            )
            # The old lock transition rejects an unconfirmed value before its
            # writer; confirm reaches the version guard. Neither can alter an
            # admitted frame or manufacture an untracked LOCK event.
            assert response.status_code == (409 if action == "confirm" else 422), response.json()
            assert response.json()["error"] == (
                "unsupported_workflow_version" if action == "confirm" else "invalid_transition"
            )
            assert rows(ctx) == before
        assert state(ctx) == current
