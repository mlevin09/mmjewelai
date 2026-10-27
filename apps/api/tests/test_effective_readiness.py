"""Current readiness must not confuse immutable historical outcomes with open issues."""

from contextlib import ExitStack
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from conftest import NOW, create_hierarchy
from jewelai_domain.rules import ReadyDecision
from jewelai_persistence import UserCorrectionIntegrityError
from jewelai_persistence.models import UserCorrectionRow
from jewelai_prompts import FinalPromptReadiness, InternalFinalPrompt, InternalFinalPromptHandoff
from sqlalchemy import select
from test_persistence import build_service
from test_prompt_enrichment_http import _client, _message
from test_prompt_enrichment_runtime import _runtime

from jewelai_api.durable_enrichment import (
    list_clarification_answer_results,
    list_user_correction_results,
)
from jewelai_api.prompt_enrichment_runtime import (
    PromptEnrichmentRuntimeService,
)


@pytest.fixture
def ready_session(engine, tmp_path):
    with ExitStack() as stack:

        def create(role="retail_client", locale="en", *, missing_dimensions=False):
            service = build_service(engine)
            runtime, store, active, report = _runtime(service, tmp_path / str(uuid4()))
            client, provider = _client(engine, runtime)
            stack.enter_context(client)
            org, _, session = create_hierarchy(client, role_id=role, locale=locale)
            sid = session.json()["session_id"]
            headers = {"X-Organization-ID": org}
            current = service.repository.get_current_revision(UUID(sid), UUID(org))
            message = _message(client, sid, org, "Explicit synthetic fixture prerequisites")
            source = {
                "kind": "message",
                "message_id": message["message_id"],
                "recorded_at": NOW.isoformat(),
            }
            design = current.design.model_dump(mode="json")
            for component, field, value in (
                ("center_stone", "shape", "oval"),
                ("center_stone", "setting", "prong_setting"),
                (
                    "center_stone",
                    "dimensions",
                    {
                        "length": {"value": 9.1, "unit": "mm"},
                        "width": {"value": 7.2, "unit": "mm"},
                        "depth": {"value": 4.8, "unit": "mm"},
                    },
                ),
                ("metal", "color", "white"),
            ):
                if missing_dimensions and field == "dimensions":
                    continue
                design[component][field] = {
                    "availability": "value",
                    "origin": "explicit",
                    "value": value,
                    "source": source,
                    "confirmed": False,
                    "locked": False,
                }
            response = client.post(
                f"/sessions/{sid}/revisions",
                headers=headers,
                json={
                    "action": "edit",
                    "expected_revision_id": str(current.revision_id),
                    "proposed_design": design,
                    "source": source,
                    "reason": "Explicit test prerequisites",
                },
            )
            assert response.status_code == 200, response.json()
            ctx = SimpleNamespace(
                service=service,
                runtime=runtime,
                store=store,
                active=active,
                report=report,
                client=client,
                provider=provider,
                sid=sid,
                org=org,
                headers=headers,
                history=[],
                immutable_decisions={},
            )
            message = _message(client, sid, org, "Gold engagement ring with an oval diamond.")
            current = service.repository.get_current_revision(UUID(sid), UUID(org))
            response = client.post(
                f"/v1/sessions/{sid}/prompt-enrichment/initial",
                headers=headers,
                json={
                    "expected_revision_id": str(current.revision_id),
                    "message_id": message["message_id"],
                },
            )
            assert response.status_code == 201, response.json()
            _capture(ctx)
            if not missing_dimensions:
                assert isinstance(ctx.history[-1].clarification_plan.rule_decision, ReadyDecision)
                assert (
                    ctx.history[-1].final_output.internal_final_prompt.readiness
                    != FinalPromptReadiness.BLOCKED
                )
            return ctx

        yield create


def _capture(ctx):
    state = ctx.runtime.get_current_state(UUID(ctx.sid), UUID(ctx.org))
    decisions = {}
    for kind, loader in (
        ("correction", list_user_correction_results),
        ("clarification", list_clarification_answer_results),
    ):
        for decision in loader(
            ctx.service.repository, session_id=UUID(ctx.sid), organization_id=UUID(ctx.org)
        ):
            decisions[(kind, decision.content_hash)] = decision.model_dump_json()
    assert all(decisions.get(key) == value for key, value in ctx.immutable_decisions.items())
    ctx.immutable_decisions = decisions
    ctx.history.append(state)
    assert ctx.provider.calls == []
    return state


def _correct(ctx, text):
    message = _message(ctx.client, ctx.sid, ctx.org, text)
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    payload = {
        "expected_revision_id": str(current.revision_id),
        "message_id": message["message_id"],
    }
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections", headers=ctx.headers, json=payload
    )
    assert response.status_code == 200, response.json()
    return response.json(), _capture(ctx)


def _answer(ctx, target, *, decision="ACCEPT"):
    state = ctx.runtime.get_current_state(UUID(ctx.sid), UUID(ctx.org))
    question = next(q for q in state.clarification_plan.questions if q.target.value == target)
    message = _message(ctx.client, ctx.sid, ctx.org, "Explicit synthetic clarification decision")
    payload = {
        "clarification_plan_id": str(state.clarification_plan_id),
        "clarification_id": question.clarification_id,
        "decision": decision,
        "expected_revision_id": str(state.authoritative_revision_id),
        "answer_id": str(uuid4()),
        "message_id": message["message_id"],
    }
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
        headers=ctx.headers,
        json=payload,
    )
    assert response.status_code == 200, response.json()
    return response.json(), _capture(ctx)


def _assert_current_ready(ctx, state):
    prompt = state.final_output.internal_final_prompt
    assert prompt.readiness != FinalPromptReadiness.BLOCKED
    assert state.status.value in {
        "final_output_ready",
        "final_output_ready_with_unresolved",
        "clarification_available",
    }
    assert not any(item.blocks_progression for item in prompt.decision_lineage)
    assert InternalFinalPrompt.model_validate_json(prompt.model_dump_json()) == prompt
    final = ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
    )
    assert final.status_code == 200, final.json()
    assert final.json()["internal_final_prompt"] == prompt.model_dump(mode="json")
    handoff = ctx.runtime.build_current_internal_final_prompt_handoff(UUID(ctx.sid), UUID(ctx.org))
    assert handoff.ready_for_downstream_preparation
    assert InternalFinalPromptHandoff.model_validate_json(handoff.model_dump_json()) == handoff
    restarted = PromptEnrichmentRuntimeService(
        ctx.service.repository,
        ctx.service.artifacts,
        ctx.store,
        knowledge_package_id=ctx.runtime.knowledge_package_id,
        knowledge_artifact_version=ctx.runtime.knowledge_artifact_version,
        active_release=ctx.active,
        validation_report=ctx.report,
        clock=lambda: NOW,
        uuid_factory=uuid4,
    )
    assert restarted.get_current_state(UUID(ctx.sid), UUID(ctx.org)) == state


@pytest.mark.parametrize("role", ("retail_client", "jewelry_designer"))
@pytest.mark.parametrize(
    ("locale", "text"),
    (
        ("en", "Do not add a halo."),
        ("ru", "Не добавляйте гало."),
        ("ru", "Do not add гало."),
    ),
)
def test_retained_constraint_is_not_an_unresolved_correction(ready_session, role, locale, text):
    ctx = ready_session(role, locale)
    response, state = _correct(ctx, text)
    assert response["outcome"] == "DEFERRED"
    correction = list_user_correction_results(
        ctx.service.repository, session_id=UUID(ctx.sid), organization_id=UUID(ctx.org)
    )[0]
    assert correction.reason.value == "constraint_retained"
    before = correction.model_dump_json()
    halo = [
        c
        for c in state.final_output.internal_final_prompt.constraints
        if c.target == "feature.halo"
    ]
    assert len(halo) == 1 and halo[0].kind == "prohibition"
    _assert_current_ready(ctx, state)
    assert (
        list_user_correction_results(
            ctx.service.repository, session_id=UUID(ctx.sid), organization_id=UUID(ctx.org)
        )[0].model_dump_json()
        == before
    )


def test_accepted_preference_resolves_only_its_causally_linked_issue(ready_session):
    ctx = ready_session()
    _, pending = _correct(ctx, "I prefer yellow with an emerald-cut center stone.")
    assert pending.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED
    history = list_user_correction_results(
        ctx.service.repository, session_id=UUID(ctx.sid), organization_id=UUID(ctx.org)
    )
    immutable = history[0].model_dump_json()
    response, partial = _answer(ctx, "metal.color")
    assert response["outcome"] == "APPLIED"
    assert partial.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED
    assert any(
        x.blocks_progression
        for x in partial.final_output.internal_final_prompt.decision_lineage
        if x.kind == "correction"
    )
    final = ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
    )
    assert final.status_code == 409
    assert partial.status.value == "final_output_blocked"
    response, resolved = _answer(ctx, "center_stone.shape")
    assert response["outcome"] == "APPLIED"
    _assert_current_ready(ctx, resolved)
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    assert current.design.metal.color.value == "yellow"
    assert current.design.center_stone.shape.value == "emerald_cut"
    assert not any(
        item.target in {"metal.color", "center_stone.shape"}
        and item.classification in {"deferred", "ambiguous"}
        for item in resolved.final_output.internal_final_prompt.unresolved_details
    )
    assert "white" not in resolved.final_output.description.text.lower()
    assert (
        list_user_correction_results(
            ctx.service.repository, session_id=UUID(ctx.sid), organization_id=UUID(ctx.org)
        )[0].model_dump_json()
        == immutable
    )


def test_five_interactions_preserve_latest_state_and_history(ready_session):
    ctx = ready_session()
    _correct(ctx, "I prefer yellow.")
    response, accepted = _answer(ctx, "metal.color")
    assert response["outcome"] == "APPLIED"
    _assert_current_ready(ctx, accepted)
    _correct(ctx, "Make the center stone emerald-cut.")
    _, final = _correct(ctx, "Do not add a halo.")
    _assert_current_ready(ctx, final)
    assert len(ctx.history) == 5
    assert [s.enrichment_cycle_number for s in ctx.history] == [1, 2, 3, 4, 5]
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    assert current.design.metal.color.value == "yellow"
    assert current.design.center_stone.shape.value == "emerald_cut"


@pytest.mark.parametrize("decision", ("SKIP", "UNKNOWN", "REJECT"))
def test_optional_answer_does_not_accept_a_preference_or_add_a_block(ready_session, decision):
    ctx = ready_session()
    _correct(ctx, "I prefer yellow.")
    _, state = _answer(ctx, "metal.color", decision=decision)
    _assert_current_ready(ctx, state)
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    assert current.design.metal.color.value == "white"
    if decision in {"SKIP", "UNKNOWN"}:
        assert any(
            d.classification == decision.lower().replace("skip", "skipped")
            for d in state.final_output.internal_final_prompt.unresolved_details
        )


def test_unrelated_later_answer_and_new_revision_do_not_clear_an_old_issue(ready_session):
    ctx = ready_session()
    _, first = _correct(ctx, "I prefer yellow.")
    original = first.final_output.internal_final_prompt.decision_lineage[0]
    _correct(ctx, "I prefer an emerald-cut center stone.")
    _, state = _answer(ctx, "center_stone.shape")
    prompt = state.final_output.internal_final_prompt
    assert prompt.readiness == FinalPromptReadiness.BLOCKED
    assert next(
        d for d in prompt.decision_lineage if d.content_hash == original.content_hash
    ).blocks_progression
    final = ctx.client.get(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
    )
    assert final.status_code == 409


@pytest.mark.parametrize("decision", ("SKIP", "UNKNOWN", "REJECT"))
def test_nonmutating_answer_continuation_preserves_another_questions_resolution(
    ready_session, decision
):
    ctx = ready_session()
    _correct(ctx, "I prefer yellow with an emerald-cut center stone.")
    _, pending = _answer(ctx, "metal.color", decision=decision)
    assert pending.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED
    _, resolved = _answer(ctx, "center_stone.shape")
    _assert_current_ready(ctx, resolved)
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    assert current.design.metal.color.value == "white"
    assert current.design.center_stone.shape.value == "emerald_cut"


@pytest.mark.parametrize("text", ("Keep the center stone unchanged.", "Gold ring.", "No halo."))
def test_supported_nonmutating_corrections_remain_nonblocking(ready_session, text):
    ctx = ready_session()
    _, state = _correct(ctx, text)
    _assert_current_ready(ctx, state)


def test_retained_constraint_does_not_hide_an_unsupported_or_missing_requirement(ready_session):
    ctx = ready_session()
    _, state = _correct(ctx, "Do not add a halo. 2 side stones.")
    assert state.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED
    assert any(
        c.target == "feature.halo" and c.kind == "prohibition"
        for c in state.final_output.internal_final_prompt.constraints
    )
    # An unrelated nonmutating action cannot discharge the unsupported target.
    _, later = _correct(ctx, "Keep the center stone unchanged.")
    assert later.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED


def test_effective_projection_is_independent_of_record_sort_order(ready_session, monkeypatch):
    ctx = ready_session()
    _correct(ctx, "No halo.")
    _correct(ctx, "I prefer yellow.")
    _, state = _answer(ctx, "metal.color")
    _assert_current_ready(ctx, state)
    repository = ctx.service.repository
    for name in ("list_user_corrections", "list_clarification_answers", "list_clarification_plans"):
        original = getattr(repository, name)
        monkeypatch.setattr(
            repository, name, lambda *args, _original=original: tuple(reversed(_original(*args)))
        )
    assert ctx.runtime.get_current_state(UUID(ctx.sid), UUID(ctx.org)) == state


def test_tampered_historical_decision_fails_closed(ready_session, engine):
    ctx = ready_session()
    _correct(ctx, "Do not add a halo.")
    with ctx.service.repository._session_factory() as db:
        row = db.scalar(
            select(UserCorrectionRow).where(UserCorrectionRow.session_id == UUID(ctx.sid))
        )
        payload = dict(row.result_payload)
        payload["reason"] = "value_already_current"
        row.result_payload = payload
        db.commit()
    with pytest.raises(UserCorrectionIntegrityError):
        ctx.runtime.get_current_state(UUID(ctx.sid), UUID(ctx.org))


def test_required_unknown_and_unrelated_optional_answer_still_block(ready_session):
    ctx = ready_session(missing_dimensions=True)
    _, pending = _correct(ctx, "I prefer yellow. Do not add a halo.")
    assert pending.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED
    _, unknown = _answer(ctx, "center_stone.dimensions", decision="UNKNOWN")
    assert unknown.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED
    _, partial = _answer(ctx, "metal.color")
    assert partial.final_output.internal_final_prompt.readiness == FinalPromptReadiness.BLOCKED
    assert partial.status.value == "blocking_clarification_unresolved"
    assert any(
        d.blocks_progression and d.outcome == "UNKNOWN"
        for d in partial.final_output.internal_final_prompt.decision_lineage
    )
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    assert current.design.center_stone.dimensions is None
