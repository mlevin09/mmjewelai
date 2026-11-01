"""R2 language journeys use real persisted commands, not DTO-only acceptance."""

from uuid import UUID, uuid4

import pytest
from jewelai_domain.models import MessageSource
from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1
from test_f04_http import f04_session, restart
from test_f05_admission import admit, rows
from test_f05_history import READY, initial
from test_f05_preview import output, state
from test_f05_release_http import answer3, consent_payload, correct3
from test_prompt_enrichment_http import _message

TEXT = {
    "EN": dict(
        keep="Keep the center stone unchanged.",
        shape="Emerald cut center stone.",
        metal="A platinum ring.",
        maybe="Maybe emerald cut center stone.",
        dimensions="Center stone 9 x 7 x 5 mm.",
        negative="No side stones. Do not change that part.",
    ),
    "RU": dict(
        keep="Сохранить центральный камень без изменений.",
        shape="Центральный камень изумрудной огранки.",
        metal="Кольцо из платины.",
        maybe="Возможно изумрудная огранка центрального камня.",
        dimensions="Центральный камень 9 x 7 x 5 мм.",
        negative="Без боковых камней. Не менять ту часть.",
    ),
    "MIXED": dict(
        keep="Сохранить центральный камень без изменений.",
        shape="Emerald cut центрального камня.",
        metal="Кольцо из platinum.",
        maybe="Maybe изумрудная огранка центрального камня.",
        dimensions="Центральный камень 9 x 7 x 5 mm.",
        negative="No side stones. Не менять ту часть.",
    ),
}


def source_setup(ctx, base, language, schema11):
    if base == "L":
        ctx.sid = UUID(ctx.legacy["session_id"])
    if schema11:
        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic schema fixture.")
        child = migrate_design_revision_v1_to_v1_1(
            old,
            revision_id=uuid4(),
            created_at=old.created_at,
            source=MessageSource(message_id=msg["message_id"], recorded_at=old.created_at),
            reason="Synthetic schema1.1 fixture",
        )
        ctx.repo.upgrade_design_session_schema_v1_1(ctx.sid, ctx.org, old.revision_id, child)
    initial(ctx, base, READY.replace(" Keep the center stone unchanged.", ""))
    ctx.runtime.continuation_enabled = True
    response, _ = admit(ctx)
    assert response.status_code == 201, response.json()
    current = correct3(ctx, response.json()["current_state"], TEXT[language]["keep"])
    assert len(current["protection_projection"]["anchors"]) == (14 if schema11 else 8)
    return current


def current_offer(current):
    return next(q["offer"] for q in current["questions"] if q["question_kind"] == "KEEP_RELEASE")


@pytest.mark.parametrize("language", ["EN", "RU", "MIXED"])
@pytest.mark.parametrize("family", [1, 2, 3, 4, 5, 6, 7, 11, 12])
@pytest.mark.parametrize("base", ["L", "F"])
def test_r2_persisted_language_journey(engine, tmp_path, language, family, base):
    # Both retained schemas and optional TEST-ONLY bindings are exercised; no
    # fixture binding is an authority to accept unsupported or protected facts.
    schema11 = family % 2 == 1
    with f04_session(
        engine, tmp_path, locale="ru" if language == "RU" else "en", binding=family % 2 == 0
    ) as ctx:
        current = source_setup(ctx, base, language, schema11)
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        text = TEXT[language]
        if family == 2:
            current = correct3(ctx, current, text["metal"])
            after = ctx.repo.get_current_revision(ctx.sid, ctx.org)
            assert after.design.metal.material.value == "platinum"
            assert after.design.center_stone == before.design.center_stone
        elif family == 12:
            current = correct3(ctx, current, text["negative"])
            after = ctx.repo.get_current_revision(ctx.sid, ctx.org)
            assert after.design.center_stone == before.design.center_stone
            assert after.design.side_stones == before.design.side_stones
        else:
            current = correct3(ctx, current, text["shape"])
            offer = current_offer(current)
            assert current["status"] == "awaiting_keep_release"
            assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
            assert output(ctx, current, projection=base == "L").status_code == 409
            if family in {3, 4, 11}:
                current = answer3(ctx, current, offer, "REJECT" if family == 4 else "ACCEPT")
                after = ctx.repo.get_current_revision(ctx.sid, ctx.org)
                assert after.design.center_stone.shape.value == (
                    "oval" if family == 4 else "emerald_cut"
                )
                for field in type(before.design.center_stone).model_fields:
                    if field != "shape":
                        assert getattr(before.design.center_stone, field) == getattr(
                            after.design.center_stone, field
                        )
                if family == 11:
                    current = correct3(ctx, current, text["metal"])
                final = output(ctx, current, projection=base == "L")
                assert final.status_code == 200, final.json()
            elif family == 5:
                current = correct3(ctx, current, text["maybe"])
                assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
                assert current["protection_projection"]["pending_requests"]
            elif family == 6:
                stale = consent_payload(ctx, current, offer, "ACCEPT")
                current = correct3(ctx, current, text["metal"])
                committed = rows(ctx)
                response = ctx.client.post(
                    f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
                    headers=ctx.headers,
                    json=stale,
                )
                assert response.status_code == 409, response.json()
                assert rows(ctx) == committed
            elif family == 7:
                current = correct3(ctx, current, text["dimensions"])
                assert len(current["protection_projection"]["pending_requests"]) == 2
                actual_cycle = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1].result
                cell = next(
                    c
                    for c in actual_cycle.native.final_matrix
                    if c.target == "center_stone.dimensions"
                )
                assert (
                    cell.value
                    == before.design.center_stone.dimensions.model_dump(mode="json")["value"]
                )
                current = answer3(ctx, current, current_offer(current), "ACCEPT")
                assert len(current["protection_projection"]["pending_requests"]) == 1
                assert (
                    ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
                    == "oval"
                )
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
        assert ctx.provider.calls == []


@pytest.mark.parametrize("language", ["EN", "RU", "MIXED"])
@pytest.mark.parametrize("base", ["L", "F"])
def test_r2_d08_existing_lock_blocks_release_without_relabel(engine, tmp_path, language, base):
    from jewelai_domain.revisions import confirm_field, lock_field, revise_design

    with f04_session(engine, tmp_path) as ctx:
        if base == "L":
            ctx.sid = UUID(ctx.legacy["session_id"])
        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic confirmed LOCK fixture."
        )
        source = MessageSource(message_id=msg["message_id"], recorded_at=old.created_at)
        design = old.design.model_dump(mode="json")
        design["center_stone"]["shape"] = dict(
            availability="value",
            origin="explicit",
            value="oval",
            source=source.model_dump(mode="json"),
            confirmed=False,
            locked=False,
        )
        child = revise_design(
            old,
            design,
            expected_revision_id=old.revision_id,
            source=source,
            reason="Synthetic supported oval",
            created_at=old.created_at,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, old.revision_id, child)
        for transition in (confirm_field, lock_field):
            next_rev = transition(
                child,
                "center_stone.shape",
                expected_revision_id=child.revision_id,
                source=source,
                reason="Synthetic explicit field authority",
                created_at=child.created_at,
            )
            ctx.repo.append_revision_cas(ctx.sid, ctx.org, child.revision_id, next_rev)
            child = next_rev
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        admitted, _ = admit(ctx)
        assert admitted.status_code == 201, admitted.json()
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        current = correct3(ctx, admitted.json()["current_state"], TEXT[language]["shape"])
        result = ctx.repo.list_user_corrections(ctx.sid, ctx.org)[-1].result_payload
        assert result["outcome"] == "REJECTED" and result["reason"] == "parser_rejected"
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
        assert not current["protection_projection"]["pending_requests"]
        assert not any(q["question_kind"] == "KEEP_RELEASE" for q in current["questions"])
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
