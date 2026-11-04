"""X27 source-backed canonical histories through real output/admission HTTP.

No prompt/renderer is mocked. Canonical visual requirements use the existing
Domain EDIT boundary before native intake; admission retains them exactly.
"""

import json
from uuid import UUID, uuid4

import pytest
from conftest import NOW
from jewelai_domain.models import MessageSource
from jewelai_domain.revisions import revise_design
from sqlalchemy import event
from test_f04_http import f04_session, restart
from test_f05_admission import admit, rows
from test_f05_history import initial
from test_f05_preview import output, state
from test_prompt_enrichment_http import _message


def seed(ctx, total, glyph, *, count=5, id_extra=0, base="L"):
    if base == "L":
        ctx.sid = UUID(ctx.legacy["session_id"])
    old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
    msg = _message(
        ctx.client,
        str(ctx.sid),
        str(ctx.org),
        "Synthetic source-backed visual requirements for capacity verification.",
    )
    source = MessageSource(message_id=msg["message_id"], recorded_at=NOW)
    design = old.design.model_dump(mode="json")
    items = [
        dict(
            constraint_id="capacity_" + str(i) + ("x" * id_extra if i == 0 else ""),
            instruction=glyph * (total // count + (i < total % count)),
        )
        for i in range(count)
    ]
    design["center_stone"]["dimensions"] = dict(availability="unknown", requirement="required")
    design["visual_constraints"] = dict(
        value=items, source=source.model_dump(mode="json"), confirmed=False, locked=False
    )
    child = revise_design(
        old,
        design,
        expected_revision_id=old.revision_id,
        source=source,
        reason="Synthetic bounded output fixture",
        created_at=NOW,
    )
    ctx.repo.append_revision_cas(ctx.sid, ctx.org, old.revision_id, child)
    initial(
        ctx,
        base,
        "A ring."
        if base == "F"
        else "A white gold ring with an oval diamond center stone in prong setting.",
    )
    ctx.runtime.continuation_enabled = True


def resolution_text(base):
    return (
        "A white gold ring with an oval diamond center stone in prong setting. "
        "Center stone 8 x 6 x 4 mm."
        if base == "F"
        else "Center stone 8 x 6 x 4 mm."
    )


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("glyph", ["A", "Ж", "😀"])
@pytest.mark.parametrize("limit", [32000, 32001])
def test_actual_ifp4_boundary_without_renderer_substitution(engine, tmp_path, glyph, limit, base):
    # L is an independently measured golden renderer baseline. Calibrate the
    # separate F renderer through an actual small persisted HTTP journey.
    fixed = 3395
    if base == "F":
        from test_f05_preservation_polarity import submit

        with f04_session(engine, tmp_path / "calibration") as calibrate:
            seed(calibrate, 1000, "A", base=base)
            admission, _ = admit(calibrate)
            assert admission.status_code == 201, admission.json()
            submit(calibrate, resolution_text(base))
            result = output(calibrate, state(calibrate), projection=False)
            assert result.status_code == 200, result.json()
            fixed = len(result.json()["internal_final_prompt"]["prompt_text"]) - 3000
    extra = next(x for x in range(3) if (limit - fixed - 2 * x) % 3 == 0)
    total = (limit - fixed - 2 * extra) // 3
    assert 5 <= total <= 10000
    with f04_session(engine, tmp_path) as ctx:
        seed(ctx, total, glyph, id_extra=extra, base=base)
        before = rows(ctx)
        admission, _ = admit(ctx)
        assert admission.status_code == 201, admission.json()
        before = rows(ctx)
        from test_f05_preservation_polarity import submit

        if limit > 32000:
            # The ordinary submitted correction reaches the actual precommit
            # output builder and must roll back, not store an oversized IFP.
            message = _message(ctx.client, str(ctx.sid), str(ctx.org), resolution_text(base))
            current = state(ctx)
            r = ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
                headers=ctx.headers,
                json=dict(
                    schema_version="3.0.0",
                    request_id=str(uuid4()),
                    message_id=message["message_id"],
                    expected_head=current["current_frame"],
                ),
            )
            assert r.status_code == 422, r.json()
            assert r.json()["error"] == "artifact_capacity_exceeded"
            assert rows(ctx) == before
            return
        submit(ctx, resolution_text(base))
        current = state(ctx)
        statements = []

        def observe(conn, cursor, sql, parameters, context, executemany):
            statements.append(sql.lstrip().split()[0].upper())

        event.listen(engine, "before_cursor_execute", observe)
        try:
            result = output(ctx, current, projection=base == "L")
            assert result.status_code == 200, result.json()
            text = result.json()["internal_final_prompt"]["prompt_text"]
            assert len(text) == limit
            assert len(text.encode("utf-8")) <= 128000
            assert glyph * 100 in text
            from jewelai_prompts.downstream_preparation import (
                GenerationPreparationError,
                build_generation_preparation,
            )
            from jewelai_prompts.downstream_preparation_v2 import build_generation_preparation_v2
            from jewelai_prompts.handoff import build_internal_final_prompt_handoff

            handoff = build_internal_final_prompt_handoff(result.json())
            for prepare in (build_generation_preparation, build_generation_preparation_v2):
                with pytest.raises(GenerationPreparationError) as rejected:
                    prepare(handoff, {}, preparation_id=uuid4(), created_at=None)
                assert rejected.value.code.value == "unsupported_source_version"
            assert not {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"}.intersection(statements)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert output(ctx, state(ctx), projection=base == "L").json() == result.json()


@pytest.mark.parametrize("base", ["L", "F"])
def test_actual_admitted_transport_capacity_and_malformed_version_are_atomic(
    engine, tmp_path, base
):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        response, command = admit(ctx)
        assert response.status_code == 201, response.json()
        before = rows(ctx)
        raw = json.dumps(command, separators=(",", ":"))
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/continuation-admissions"
        for length, expected in [(1048576, 201), (1048577, 422)]:
            data = raw + " " * (length - len(raw.encode("utf-8")))
            r = ctx.client.post(
                path, headers={**ctx.headers, "Content-Type": "application/json"}, content=data
            )
            assert r.status_code == expected, r.json()
            assert rows(ctx) == before
        for body in [
            raw[:-1] + ',"schema_version":"1.0.0"}',
            raw.replace('"1.0.0"', '"3.0.0"', 1),
            '{"schema_version":NaN}',
        ]:
            r = ctx.client.post(
                path, headers={**ctx.headers, "Content-Type": "application/json"}, content=body
            )
            assert r.status_code == 422, r.json()
            assert rows(ctx) == before


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("limit", [20000, 20001])
def test_actual_description_guard_from_canonical_history(engine, tmp_path, limit, base):
    from test_f05_preservation_polarity import submit

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        admission, _ = admit(ctx)
        assert admission.status_code == 201, admission.json()
        current = admission.json()["current_state"]
        current = submit(ctx, "Center stone qx" + "q" * 85, current=current)["current_state"]
        baseline = len(current["description"]["text"])
        current = submit(ctx, "Center stone qy" + "q" * 85, current=current)["current_state"]
        # Source-backed unresolved wording is disclosed, never canonicalized.
        overhead = len(current["description"]["text"]) - baseline - 100
        assert 0 < overhead < 500
        assert "Center stone qy" in current["description"]["text"]
        index = 0
        while limit - len(current["description"]["text"]) - overhead > 1900:
            bulk = min(1900, limit - len(current["description"]["text"]) - 2 * overhead - 100)
            assert bulk >= 16
            text = "Center stone qz" + chr(97 + index) + "q" * (bulk - 16)
            current = submit(ctx, text, current=current)["current_state"]
            index += 1
            assert index < 20
        size = limit - len(current["description"]["text"]) - overhead
        assert 16 <= size <= 2000
        text = "Center stone qzz" + "q" * (size - 16)
        message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
        before = rows(ctx)
        r = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                request_id=str(uuid4()),
                message_id=message["message_id"],
                expected_head=current["current_frame"],
            ),
        )
        assert r.status_code == (200 if limit == 20000 else 422), r.json()
        if limit > 20000:
            assert r.json()["error"] == "artifact_capacity_exceeded"
            assert rows(ctx) == before
        else:
            current = state(ctx)
            assert len(current["description"]["text"]) == 20000
            assert len(current["description"]["text"].encode("utf-8")) <= 80000
            assert text in current["description"]["text"]
            with restart(ctx, engine):
                ctx.runtime.continuation_enabled = True
                assert state(ctx) == current
