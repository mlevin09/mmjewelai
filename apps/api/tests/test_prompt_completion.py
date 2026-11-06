"""Opt-in actual HTTP commands, SQLite transaction/restart; no network providers."""

from functools import partial
from uuid import UUID, uuid4

import pytest
import test_prompt_enrichment_composition as composition
from jewelai_prompts.completion import CompletionRegistry
from test_conversation import correct, read
from test_f04_http import answer_question, f04_session, restart
from test_f05_history import initial
from test_prompt_enrichment_http import _message


@pytest.fixture
def enabled(monkeypatch):
    policy = CompletionRegistry.model_validate(
        dict(
            registry_id="test_only_completion",
            version="1.0.0",
            review_status="APPROVED",
            rules=[
                dict(
                    target_path="center_stone.dimensions",
                    when_jewelry_type="ring",
                    proposed_value={
                        "length": {"value": 8.0, "unit": "mm"},
                        "width": {"value": 6.0, "unit": "mm"},
                        "depth": {"value": 4.0, "unit": "mm"},
                    },
                    rule_id="test_oval_size",
                    rule_version="1.0.0",
                    rationale="TEST ONLY quantitative policy; not professional approval",
                    requires={"center_stone.material": "diamond", "center_stone.shape": "oval"},
                )
            ],
            eligibility=[
                dict(jewelry_type="ring", target=t, mode="default_or_omit")
                for t in [
                    "center_stone.dimensions",
                    "center_stone.setting",
                    "center_stone.cut",
                    "metal.color",
                ]
            ],
        )
    )
    monkeypatch.setattr(
        composition, "create_app", partial(composition.create_app, completion_registry=policy)
    )
    return policy


def command(ctx, state, choice="NO", **changes):
    msg = _message(ctx.client, str(ctx.sid), str(ctx.org), choice)
    body = dict(
        schema_version="1.0.0",
        request_id=str(uuid4()),
        message_id=msg["message_id"],
        expected_frame=state["state"]["current_frame"],
        anything_else=choice,
    )
    body.update(changes)
    return body, ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions", headers=ctx.headers, json=body
    )


def current(ctx):
    return ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions/current", headers=ctx.headers
    )


def test_complete_unknown_refine_restart_replay_and_latest(
    engine, tmp_path, enabled, record_property
):
    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F", "A yellow gold engagement ring with an oval diamond center stone.")
        state = read(ctx)
        context = current(ctx)
        assert context.status_code == 200, context.json()
        assert context.json()["status"] == "AWAITING_COMPLETION"
        assert context.json()["question"]["choices"] == ["YES", "NO"]
        for decision in ("UNKNOWN", "SKIP"):
            native = ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
            ).json()
            assert native["clarification_questions"], "Expected actual contextual clarification"
            response = answer_question(ctx, native, native["clarification_questions"][0], decision)
            assert response.status_code == 200, response.json()
            state = read(ctx)
        _, yes = command(ctx, state, "YES")
        assert yes.status_code == 200, yes.json()
        assert yes.json()["status"] == "EDITING" and yes.json()["final_prompt"] is None
        state = correct(ctx, state, "Use a prong setting.")
        before = state
        body, done = command(ctx, state)
        assert done.status_code == 200, done.json()
        result = done.json()
        final = result["final_prompt"]
        assert final["schema_version"] == "6.0.0"
        assert final["assumptions"]
        assert (
            final["effective_revision"]["design"]["center_stone"]["dimensions"]["origin"]
            == "assumed"
        )
        replay = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions", headers=ctx.headers, json=body
        )
        assert replay.status_code == 200, replay.json()
        assert replay.json()["replayed"] and replay.json()["final_prompt"] == final
        unchanged = read(ctx)
        assert unchanged["revision"] == before["revision"]
        assert unchanged["state"] == before["state"]
        with restart(ctx, engine):
            assert current(ctx).json()["final_prompt"] == final
        changed = correct(ctx, read(ctx), "Use platinum. Center stone 9 x 7 x 4 mm.")
        assert current(ctx).status_code == 409
        stale = {**body, "request_id": str(uuid4())}
        assert (
            ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions",
                headers=ctx.headers,
                json=stale,
            ).status_code
            == 409
        )
        _, new = command(ctx, changed)
        assert new.status_code == 200, new.json()
        newfinal = new.json()["final_prompt"]
        effective = {f["concrete_target"]: f["value"] for f in newfinal["effective_parameters"]}
        assert effective["metal.material"] == "platinum"
        dims = newfinal["effective_revision"]["design"]["center_stone"]["dimensions"]
        assert dims["origin"] == "explicit" and dims["value"]["length"]["value"] == 9
        assert not newfinal["assumptions"]
        record_property("initial_ifp6_prompt", final["prompt_text"])
        record_property("corrected_ifp6_prompt", newfinal["prompt_text"])
        record_property("initial_policy_sha256", final["policy_sha256"])
        assert "8.0" not in newfinal["prompt_text"]
        assert 'metal.material: "gold"' not in newfinal["prompt_text"]
        old = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions", headers=ctx.headers, json=body
        )
        assert old.status_code == 200 and not old.json()["is_current"]
        assert ctx.provider.calls == []


def test_completion_scope_idempotency_and_tamper(engine, tmp_path, enabled):
    from copy import deepcopy

    from jewelai_persistence.models import PromptCompletionRow
    from sqlalchemy import select

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        state = read(ctx)
        body, done = command(ctx, state)
        assert done.status_code == 200, done.json()
        assert not done.json()["final_prompt"]["assumptions"]
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions"
        conflict = {**body, "anything_else": "YES"}
        assert ctx.client.post(path, headers=ctx.headers, json=conflict).status_code == 409
        assert (
            ctx.client.get(
                path + "/current", headers={**ctx.headers, "Authorization": "Bearer test-outsider"}
            ).status_code
            == 404
        )
        assert (
            ctx.client.get(
                path + "/current", headers={**ctx.headers, "Authorization": ""}
            ).status_code
            == 401
        )
        _, yes = command(ctx, state, "YES")
        assert yes.status_code == 200 and current(ctx).json()["status"] == "EDITING"
        old = ctx.client.post(path, headers=ctx.headers, json=body)
        assert old.json()["replayed"] and not old.json()["is_current"]
        with ctx.repo._session_factory.begin() as db:
            rows = list(
                db.scalars(
                    select(PromptCompletionRow).order_by(PromptCompletionRow.sequence_number)
                )
            )
            assert len(rows) == 2
            payload = deepcopy(rows[-1].payload)
            payload["message_sha256"] = "0" * 64
            rows[-1].payload = payload
        assert current(ctx).status_code == 500


def test_completion_rejects_pending_keep_atomically(engine, tmp_path, enabled):
    from jewelai_persistence.models import PromptCompletionRow
    from sqlalchemy import func, select
    from test_f05_admission import admit
    from test_f05_release_http import correct3

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        ctx.runtime.continuation_enabled = True
        response, _ = admit(ctx)
        assert response.status_code == 201, response.json()
        state = read(ctx)
        pending = correct3(ctx, state["state"], "Emerald cut center stone.")
        assert pending["protection_projection"]["pending_requests"]
        before = read(ctx)
        _, denied = command(ctx, before)
        assert denied.status_code == 409 and denied.json()["error"] == "pending_keep_consent", (
            denied.json()
        )
        after = read(ctx)
        assert after["revision"] == before["revision"] and after["state"] == before["state"]
        with ctx.repo._session_factory() as db:
            assert db.scalar(select(func.count()).select_from(PromptCompletionRow)) == 0
        from test_f05_release_http import answer3

        offer = next(
            q["offer"] for q in pending["questions"] if q["question_kind"] == "KEEP_RELEASE"
        )
        answer3(ctx, pending, offer, "REJECT")
        _, final = command(ctx, read(ctx))
        assert final.status_code == 200, final.json()
        assert (
            final.json()["final_prompt"]["effective_revision"]["design"]["center_stone"]["shape"][
                "value"
            ]
            == "oval"
        )


def test_completion_conflicting_material_is_not_defaulted(engine, tmp_path, enabled):
    from jewelai_persistence.models import PromptCompletionRow
    from sqlalchemy import func, select

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F", "A gold or platinum ring with an oval diamond.")
        before = read(ctx)
        _, denied = command(ctx, before)
        assert denied.status_code == 409
        assert denied.json()["error"] in {"conflicting_evidence", "mandatory_decision_unresolved"}
        after = read(ctx)
        assert after["revision"] == before["revision"] and after["state"] == before["state"]
        with ctx.repo._session_factory() as db:
            assert db.scalar(select(func.count()).select_from(PromptCompletionRow)) == 0


def test_completion_validation_failure_rolls_back_append(engine, tmp_path, enabled, monkeypatch):
    from jewelai_persistence.models import PromptCompletionRow
    from sqlalchemy import func, select

    from jewelai_api.continuation_preview import ContinuationReadError

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        before = read(ctx)

        def fail(*args):
            raise ContinuationReadError(500, "injected_validation_failure", "TEST ONLY")

        monkeypatch.setattr(ctx.app.state.completion_service, "_validate", fail)
        _, denied = command(ctx, before)
        assert denied.status_code == 500
        with ctx.repo._session_factory() as db:
            assert db.scalar(select(func.count()).select_from(PromptCompletionRow)) == 0
        after = read(ctx)
        assert after["revision"] == before["revision"] and after["state"] == before["state"]


def test_completion_write_reservation_never_rewinds_cached_revision(
    engine, tmp_path, enabled, monkeypatch
):
    import jewelai_persistence.completion as storage
    from sqlalchemy.orm.attributes import set_committed_value

    with f04_session(engine, tmp_path, binding=True) as ctx:
        initial(ctx, "F")
        original = read(ctx)
        state = correct(ctx, original, "Use platinum.")
        old_revision = ctx.repo.get_revision(
            ctx.sid, UUID(original["revision"]["revision_id"]), ctx.org
        ).revision_id
        authorize = storage._authorize_and_lock

        def stale_cache(*args):
            session = authorize(*args)
            # A stale ORM read must never become the value written by a reservation.
            set_committed_value(session, "current_revision_id", old_revision)
            return session

        monkeypatch.setattr(storage, "_authorize_and_lock", stale_cache)
        _, result = command(ctx, state)
        assert result.status_code == 200, result.json()
        actual = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert str(actual.revision_id) == state["revision"]["revision_id"]
        assert actual.design.metal.material.value == "platinum"
