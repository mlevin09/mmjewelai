"""Real native HTTP setup and consistent read-only continuation frame restoration."""

from uuid import UUID, uuid4

import pytest
from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1
from sqlalchemy import event
from test_f04_http import f04_session, restart
from test_prompt_enrichment_http import _message

from jewelai_api.continuation_history import read_native_frame

READY = (
    "A white gold ring with an oval diamond center stone in prong setting. "
    "Center stone 8 x 6 x 4 mm. Keep the center stone unchanged."
)


def initial(ctx, base, text=READY):
    if base == "L":
        ctx.sid = UUID(ctx.legacy["session_id"])
    current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    payload = dict(expected_revision_id=str(current.revision_id), message_id=message["message_id"])
    if base == "F":
        payload["schema_version"] = "2.0.0"
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/initial", headers=ctx.headers, json=payload
    )
    assert response.status_code == 201, response.json()


def frame(ctx):
    with ctx.repo.read_enrichment_history(ctx.sid, ctx.org) as reader:
        return read_native_frame(ctx.runtime, reader, ctx.sid, ctx.org)


@pytest.mark.parametrize("base", ["L", "F"])
def test_scoped_frame_ignores_unprocessed_messages_and_reads_issue_no_writes(
    engine, tmp_path, base
):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        first = frame(ctx)
        _message(ctx.client, str(ctx.sid), str(ctx.org), "Unprocessed synthetic message.")
        statements = []

        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            second = frame(ctx)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert first.frame == second.frame
        assert first.protection == second.protection
        assert len(first.protection.anchors) == 8
        assert not set(statements).intersection(
            {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}
        )
        with restart(ctx, engine):
            assert frame(ctx).frame == first.frame
        assert ctx.provider.calls == []


def test_schema11_read_frame_covers_all_fourteen_fields(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic schema upgrade.")
        source = MessageSource(message_id=msg["message_id"], recorded_at=old.created_at)
        migrated = migrate_design_revision_v1_to_v1_1(
            old,
            revision_id=uuid4(),
            created_at=old.created_at,
            source=source,
            reason="Explicit local test schema1.1 fixture",
        )
        ctx.repo.upgrade_design_session_schema_v1_1(ctx.sid, ctx.org, old.revision_id, migrated)
        initial(ctx, "F")
        current = frame(ctx)
        assert len(current.protection.anchors) == 14
        assert {a.target.concrete_target for a in current.protection.anchors}.issuperset(
            {
                "center_stone.treatment_status",
                "center_stone.material_origin_status",
                "center_stone.geographic_origin",
                "center_stone.cut_style_class",
            }
        )
