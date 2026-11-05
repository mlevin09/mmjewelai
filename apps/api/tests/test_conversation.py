"""Actual scoped HTTP conversation projection over existing L/F durable workflows."""

from copy import deepcopy
from uuid import UUID

import pytest
from jewelai_persistence.models import MessageRow
from sqlalchemy import event, update
from test_f04_http import answer, f04_session, restart
from test_f04_http import initial as initial_f
from test_f05_history import initial
from test_prompt_enrichment_http import _message


def read(ctx):
    response = ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/conversation", headers=ctx.headers
    )
    assert response.status_code == 200, response.json()
    assert response.headers["cache-control"] == "no-store, private"
    return response.json()


def correct(ctx, snapshot, text):
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    frame = snapshot["state"]["current_frame"]
    body = dict(message_id=message["message_id"], expected_revision_id=frame["revision_id"])
    if snapshot["state"]["retained_base"] == "F":
        body.update(
            schema_version="2.0.0",
            expected_enrichment_cycle_id=frame["enrichment_cycle_id"],
            expected_enrichment_result_hash=frame["enrichment_result_hash"],
            expected_clarification_plan_hash=frame["plan_hash"],
        )
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections", headers=ctx.headers, json=body
    )
    assert response.status_code == 200, response.json()
    return read(ctx)


@pytest.mark.parametrize("base", ["L", "F"])
def test_conversation_multiturn_current_state_and_restart_no_writes(engine, tmp_path, base):
    with f04_session(engine, tmp_path) as ctx:
        if base == "L":
            ctx.sid = UUID(ctx.legacy["session_id"])
        assert read(ctx)["state"] is None
        initial(ctx, base, "I want a white gold ring with an oval diamond.")
        first = read(ctx)
        assert first["revision"]["design"]["metal"]["material"]["value"] == "gold"
        stone = deepcopy(first["revision"]["design"]["center_stone"])
        current = correct(ctx, first, "Change the metal to platinum.")
        assert current["revision"]["design"]["metal"]["material"]["value"] == "platinum"
        current = correct(ctx, current, "Keep the center stone unchanged. Add a delicate band.")
        current = correct(ctx, current, "A yellow gold ring.")
        assert current["revision"]["design"]["center_stone"] == stone
        assert current["state"]["protection_projection"]["roots"]
        assert len([e for e in current["events"] if e["kind"] == "user"]) == 4
        assert len([e for e in current["events"] if e["kind"] == "decision"]) == 3
        assert all(
            r.result_payload["parsed_correction"]["parse_version"] == "1.2.0"
            for r in ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        )
        committed = (
            ctx.repo.list_revisions(ctx.sid, ctx.org),
            ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org),
        )
        statements = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            with restart(ctx, engine):
                assert read(ctx) == current
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}
        assert committed == (
            ctx.repo.list_revisions(ctx.sid, ctx.org),
            ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org),
        )
        assert ctx.provider.calls == []


def test_conversation_real_question_answer_scope_and_tamper(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial_f(ctx, "A gold or platinum ring.")
        before = read(ctx)
        assert any(e["kind"] == "question" for e in before["events"])
        response, _ = answer(ctx, state, value="gold")
        assert response.status_code == 200, response.json()
        after = read(ctx)
        assert any(e["kind"] == "decision" and e["outcome"] == "APPLIED" for e in after["events"])
        reader_headers = {"Authorization": "Bearer test-ui-reader"}
        reader = ctx.client.get("/me", headers=reader_headers).json()
        membership = ctx.client.post(
            f"/organizations/{ctx.org}/memberships",
            json={"principal_id": reader["principal_id"], "role": "member"},
        )
        assert membership.status_code == 201, membership.json()
        second_user = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/conversation",
            headers={**reader_headers, **ctx.headers},
        )
        assert second_user.status_code == 200, second_user.json()
        assert second_user.json() == after
        other = ctx.client.post(
            "/organizations", json={"name": "Unrelated test organization"}
        ).json()
        forbidden = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/conversation",
            headers={"X-Organization-ID": other["organization_id"]},
        )
        assert forbidden.status_code == 404
        assert "gold" not in forbidden.text
        outsider = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/conversation",
            headers={"Authorization": "Bearer test-outside-user", **ctx.headers},
        )
        assert outsider.status_code == 404
        assert "gold" not in outsider.text
        rejected_write = ctx.client.post(
            f"/sessions/{ctx.sid}/messages",
            headers={"Authorization": "Bearer test-outside-user", **ctx.headers},
            json={"content": "Synthetic unauthorized message"},
        )
        assert rejected_write.status_code == 404
        assert read(ctx) == after
        message = next(
            e
            for e in after["events"]
            if e["kind"] == "user" and e["text"] == "A gold or platinum ring."
        )
        with engine.begin() as db:
            db.execute(
                update(MessageRow)
                .where(MessageRow.message_id == UUID(message["message_id"]))
                .values(content="Tampered source")
            )
        broken = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/conversation", headers=ctx.headers
        )
        assert broken.status_code == 500
        assert broken.json()["error"] == "invalid_durable_history"
        assert "Tampered source" not in broken.text
