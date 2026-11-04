"""F06 internal builder opt-in on actual source-verified HTTP/restart frames.

No public version-5 API is introduced. The test-only observer explicitly invokes
that builder on the exact snapshot already obtained by the existing scoped read.
"""

import json
import os
from pathlib import Path

from jewelai_prompts.final_prompt_v5 import assemble_internal_final_prompt_v5
from jewelai_prompts.handoff import build_internal_final_prompt_handoff
from sqlalchemy import event
from test_f04_http import f04_session, restart
from test_f05_admission import admit
from test_f05_history import initial
from test_f05_preview import output, state
from test_f05_release_http import correct3

from jewelai_api import continuation_preview


def test_f06_explicit_builder_current_http_correction_restart(engine, tmp_path, monkeypatch):
    captured = []
    original = continuation_preview.assemble_internal_final_prompt_v4

    def observe(snapshot, **kwargs):
        old = original(snapshot, **kwargs)
        current = assemble_internal_final_prompt_v5(snapshot, **kwargs)
        left, right = old.internal_final_prompt, current.internal_final_prompt
        for name in (
            "design_facts",
            "constraints",
            "constraint_evidence",
            "decision_lineage",
            "current_frame",
            "knowledge_release",
            "artifact_versions",
            "readiness",
            "unresolved_details",
            "protection_projection",
        ):
            assert getattr(left, name) == getattr(right, name), name
        captured.append((snapshot, old, current))
        return old

    monkeypatch.setattr(continuation_preview, "assemble_internal_final_prompt_v4", observe)
    with f04_session(engine, tmp_path, locale="en") as ctx:
        initial(ctx, "F")
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        before = state(ctx)
        old_revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        changed = correct3(ctx, before, "A platinum ring.")
        revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert revision.design.metal.material.value == "platinum"
        assert revision.design.center_stone == old_revision.design.center_stone
        statements = []

        def sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", sql)
        try:
            final = output(ctx, changed, projection=False)
            assert final.status_code == 200, final.json()
            snapshot, old, new = captured[-1]
            assert old.internal_final_prompt.schema_version == "4.0.0"
            assert "KEEP" in new.description.text
            assert "platinum" in new.description.text
            assert "component.center_stone" not in new.description.text
            assert new.internal_final_prompt.protection_projection.roots
            assert new.internal_final_prompt.current_frame.revision_id == revision.revision_id
            assert output(ctx, before, projection=False).status_code == 409
            unsupported = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output?output_version=5.0.0",
                headers=ctx.headers,
            )
            assert unsupported.status_code == 409
            assert unsupported.json()["error"] == "unsupported_output_version"
        finally:
            event.remove(engine, "before_cursor_execute", sql)
        assert not set(statements).intersection({"INSERT", "UPDATE", "DELETE", "ALTER", "DROP"})
        committed = (
            ctx.repo.list_revisions(ctx.sid, ctx.org),
            ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org),
        )
        handoff = build_internal_final_prompt_handoff(new)
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == changed
            assert output(ctx, changed, projection=False).json() == final.json()
            restored = captured[-1][2]
            assert restored.model_dump_json() == new.model_dump_json()
            assert build_internal_final_prompt_handoff(restored) == handoff
            assert committed == (
                ctx.repo.list_revisions(ctx.sid, ctx.org),
                ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org),
            )
        assert ctx.provider.calls == []
        folder = os.getenv("F06_EVIDENCE_DIR")
        if folder:
            root = Path(folder)
            root.mkdir(parents=True, exist_ok=True)
            (root / "http-f05-correction-restart.json").write_text(
                json.dumps(
                    dict(
                        backend=engine.dialect.name,
                        internal_only_opt_in=True,
                        initial_canonical=old_revision.model_dump(mode="json"),
                        canonical=revision.model_dump(mode="json"),
                        snapshot=snapshot.model_dump(mode="json"),
                        legacy_output=old.model_dump(mode="json"),
                        output=new.model_dump(mode="json"),
                        handoff=handoff.model_dump(mode="json"),
                        restart_equal=True,
                        zero_write_read=True,
                        provider_calls=0,
                        stale_status=409,
                        public_output5_status=unsupported.status_code,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
