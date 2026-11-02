"""F05-FA-01 source authority through real admitted correction and restart."""

from uuid import uuid4

import pytest
from test_f04_http import f04_session, restart
from test_f05_admission import admit
from test_f05_history import READY, initial
from test_f05_preview import output, state
from test_prompt_enrichment_http import _message


def submit(ctx, text, *, current=None):
    current = state(ctx) if current is None else current
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
        headers=ctx.headers,
        json=dict(
            schema_version="3.0.0",
            request_id=str(uuid4()),
            message_id=message["message_id"],
            expected_head=current["current_frame"],
        ),
    )
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize(
    "text,locale",
    [
        ("Maybe keep the center stone shape unchanged.", "en"),
        ("Возможно сохранить центральный камень без изменений.", "ru"),
        ("Не нужно сохранить центральный камень без изменений.", "ru"),
        ("Maybe preserve the center stone shape unchanged. A platinum ring.", "en"),
    ],
)
def test_uncertain_or_negated_preservation_cannot_create_authority(
    engine, tmp_path, base, text, locale, monkeypatch
):
    from jewelai_api import continuation_preview

    actual_assembly = continuation_preview.assemble_internal_final_prompt_v4
    observed = []

    def observe(*args, **kwargs):
        result = actual_assembly(*args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr(continuation_preview, "assemble_internal_final_prompt_v4", observe)
    with f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, base, READY.replace(" Keep the center stone unchanged.", ""))
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        assert not state(ctx)["protection_projection"]["roots"]
        submit(ctx, text)
        current = state(ctx)
        assert not current["protection_projection"]["roots"], current["protection_projection"]
        if "platinum" in text:
            assert (
                ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material.value
                == "platinum"
            )
        submit(ctx, "Emerald cut center stone.")
        current = state(ctx)
        assert not current["protection_projection"]["pending_requests"]
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "emerald_cut"
        )
        final = output(ctx, current, projection=base == "L")
        expected_status = 409 if base == "L" and text.startswith("Не нужно") else 200
        assert final.status_code == expected_status, final.json()
        if expected_status == 409:
            assert final.json()["error"] == "final_output_blocked"
            assert not current["protection_projection"]["roots"]
        assert observed
        assert not observed[-1].internal_final_prompt.protection_projection.roots
        saved = final.json()
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
            assert output(ctx, current, projection=base == "L").json() == saved


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize(
    "text,locale,count",
    [
        ("Keep the center stone shape unchanged.", "en", 1),
        ("I do not want a halo and keep the center stone shape unchanged.", "en", 1),
        ("Не хочу гало и сохранить центральный камень без изменений.", "ru", 8),
        ("Сохранить центральный камень без изменений.", "ru", 8),
        ("Хочу сохранить центральный камень без изменений.", "ru", 8),
        ("I would like to keep the center stone shape unchanged.", "en", 1),
        ("A platinum ring. Сохранить центральный камень без изменений.", "en", 8),
    ],
)
def test_affirmative_preservation_scope_remains_authoritative(
    engine, tmp_path, base, text, locale, count
):
    with f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, base, READY.replace(" Keep the center stone unchanged.", ""))
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        assert a.status_code == 201, a.json()
        submit(ctx, text)
        current = state(ctx)
        assert len(current["protection_projection"]["anchors"]) == count
        submit(ctx, "Emerald cut center stone.")
        current = state(ctx)
        assert current["protection_projection"]["pending_requests"]
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "oval"
        )
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize(
    "text",
    [
        "Maybe keep the center stone shape unchanged.",
        "Не нужно сохранить центральный камень без изменений.",
    ],
)
def test_unresolved_preservation_is_not_cancellation_of_existing_keep(engine, tmp_path, base, text):
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        assert a.status_code == 201, a.json()
        original = state(ctx)["protection_projection"]
        submit(ctx, text)
        current = state(ctx)
        assert current["protection_projection"]["roots"] == original["roots"]
        assert current["protection_projection"]["anchors"] == original["anchors"]
        submit(ctx, "Emerald cut center stone.")
        current = state(ctx)
        assert current["protection_projection"]["pending_requests"]
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "oval"
        )
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize(
    "text,locale",
    [
        ("Do you think we should keep the center stone shape unchanged?", "en"),
        ("Нужно ли сохранить центральный камень без изменений?", "ru"),
        ("Probably keep the center stone shape unchanged.", "en"),
        ("Наверное сохранить центральный камень без изменений.", "ru"),
        ("Вероятно сохранить центральный камень без изменений.", "ru"),
        ("Необязательно сохранить центральный камень без изменений.", "ru"),
        ("Незачем сохранить центральный камень без изменений.", "ru"),
        ("I refuse to keep the center stone shape unchanged.", "en"),
        ("Keep the center stone unchanged, probably.", "en"),
        ("Сохранить центральный камень без изменений необязательно.", "ru"),
    ],
)
def test_nonaffirmative_preservation_is_not_authority(
    engine, tmp_path, monkeypatch, base, text, locale
):
    from jewelai_api import continuation_preview

    real = continuation_preview.assemble_internal_final_prompt_v4
    seen = []

    def observe(*args, **kwargs):
        actual = real(*args, **kwargs)
        seen.append(actual)
        return actual

    monkeypatch.setattr(continuation_preview, "assemble_internal_final_prompt_v4", observe)
    with f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, base, READY.replace(" Keep the center stone unchanged.", ""))
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        assert a.status_code == 201, a.json()
        submit(ctx, text)
        current = state(ctx)
        assert not current["protection_projection"]["roots"]
        submit(ctx, "Emerald cut center stone.")
        current = state(ctx)
        assert not current["protection_projection"]["pending_requests"]
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
            == "emerald_cut"
        )
        assert not seen[-1].internal_final_prompt.protection_projection.roots
        result = output(ctx, current, projection=base == "L")
        # Existing independent native obligations retain their own readiness.
        assert result.status_code in (200, 409), result.json()
        if result.status_code == 409:
            assert result.json()["error"] == "final_output_blocked"
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
            replay = output(ctx, current, projection=base == "L")
            assert replay.status_code == result.status_code and replay.json() == result.json()
