"""X14 actual retained-profile native answer combinations, not DTO projections."""

from uuid import uuid4

import pytest
from test_f04_http import f04_session, restart
from test_f05_admission import admit, rows
from test_f05_history import READY, initial
from test_f05_preservation_polarity import submit
from test_f05_preview import output, state
from test_f05_release_http import consent_payload
from test_prompt_enrichment_http import _message


def _exercise_native(
    engine, tmp_path, base, scope, stage, action, relation, *, lock_material=False
):
    value = "oval" if stage == "pending" else "emerald_cut"
    preference = (
        "yellow metal"
        if relation == "unrelated"
        else (
            ("oval" if value == "oval" else "emerald cut")
            if relation == "same"
            else ("emerald cut" if value == "oval" else "oval")
        )
        + " center stone"
    )
    with f04_session(engine, tmp_path) as ctx:
        if lock_material:
            from uuid import UUID

            from jewelai_domain.models import MessageSource
            from jewelai_domain.revisions import confirm_field, lock_field, revise_design

            if base == "L":
                ctx.sid = UUID(ctx.legacy["session_id"])
            old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
            msg = _message(
                ctx.client, str(ctx.sid), str(ctx.org), "Synthetic explicit diamond LOCK."
            )
            src = MessageSource(message_id=msg["message_id"], recorded_at=old.created_at)
            design = old.design.model_dump(mode="json")
            design["center_stone"]["material"] = dict(
                value="diamond", source=src.model_dump(mode="json"), confirmed=False, locked=False
            )
            child = revise_design(
                old,
                design,
                expected_revision_id=old.revision_id,
                source=src,
                reason="Synthetic known material",
                created_at=old.created_at,
            )
            ctx.repo.append_revision_cas(ctx.sid, ctx.org, old.revision_id, child)
            for transition in (confirm_field, lock_field):
                next_rev = transition(
                    child,
                    "center_stone.material",
                    expected_revision_id=child.revision_id,
                    source=src,
                    reason="Synthetic LOCK authority",
                    created_at=child.created_at,
                )
                ctx.repo.append_revision_cas(ctx.sid, ctx.org, child.revision_id, next_rev)
                child = next_rev
        initial(ctx, base, READY.replace(" Keep the center stone unchanged.", ""))
        ctx.runtime.continuation_enabled = True
        a, _ = admit(ctx)
        assert a.status_code == 201, a.json()
        submit(
            ctx,
            "Keep the center stone unchanged."
            if scope == "generic"
            else "Keep the center stone shape unchanged.",
        )
        pending = submit(ctx, "Emerald cut center stone.")["current_state"]
        if stage == "reanchored":
            offer = next(
                q["offer"] for q in pending["questions"] if q["question_kind"] == "KEEP_RELEASE"
            )
            r = ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
                headers=ctx.headers,
                json=consent_payload(ctx, pending, offer, "ACCEPT"),
            )
            assert r.status_code == 200, r.json()
        submit(ctx, "I prefer " + preference + ".")
        current = state(ctx)
        questions = [
            q["native_question"]
            for q in current["questions"]
            if q["question_kind"] == "NATIVE"
            and q["native_question"]["category"] == "preference_acceptance"
        ]
        if not questions:
            # L has no preference question for an already satisfied source.
            # Prove absence from the actual sealed plan; do not forge an offer.
            assert base == "L" and relation == "same"
            assert (
                ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value
                == value
            )
            with restart(ctx, engine):
                ctx.runtime.continuation_enabled = True
                assert state(ctx) == current
            return
        q = questions[0]
        option = q["options"][0]
        native = dict(
            retained_base=base,
            decision=action,
            selected_option=option["value"] if action == "SELECT_OPTION" else None,
        )
        if base == "F":
            native["selected_option_id"] = (
                option["option_id"] if action == "SELECT_OPTION" else None
            )
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic native answer."
        )
        before = rows(ctx)
        r = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=dict(
                schema_version="3.0.0",
                answer_kind="NATIVE",
                answer_id=str(uuid4()),
                message_id=message["message_id"],
                expected_head=current["current_frame"],
                clarification_plan_id=current["current_frame"]["plan_id"],
                clarification_id=q["clarification_id"],
                native=native,
            ),
        )
        assert r.status_code == (409 if relation == "different" else 200), r.json()
        if relation == "different":
            assert r.json()["error"] == "keep_release_confirmation_required"
            assert rows(ctx) == before
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.shape.value == value
        )
        if lock_material:
            locked = ctx.repo.get_current_revision(ctx.sid, ctx.org).design.center_stone.material
            assert locked.locked and locked == before[0].design.center_stone.material
        current = state(ctx)
        final = output(ctx, current, projection=base == "L")
        assert final.status_code in (200, 409), final.json()
        with restart(ctx, engine):
            ctx.runtime.continuation_enabled = True
            assert state(ctx) == current
            replay = output(ctx, current, projection=base == "L")
            assert replay.status_code == final.status_code and replay.json() == final.json()


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("scope", ["generic", "shape"])
@pytest.mark.parametrize("stage", ["pending", "reanchored"])
@pytest.mark.parametrize("action", ["ACCEPT", "SELECT_OPTION"])
@pytest.mark.parametrize("relation", ["same", "different", "unrelated"])
def test_native_guard_full_matrix(engine, tmp_path, base, scope, stage, action, relation):
    _exercise_native(engine, tmp_path, base, scope, stage, action, relation)


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("scope", ["generic", "shape"])
@pytest.mark.parametrize("stage", ["pending", "reanchored"])
@pytest.mark.parametrize("action", ["ACCEPT", "SELECT_OPTION"])
def test_native_guard_retains_independent_locked_wrapper(
    engine, tmp_path, base, scope, stage, action
):
    _exercise_native(engine, tmp_path, base, scope, stage, action, "different", lock_material=True)
