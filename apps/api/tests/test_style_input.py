"""Ordinary style wording must cross the persisted enrichment HTTP boundary safely."""

from contextlib import ExitStack
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from conftest import NOW, create_hierarchy
from jewelai_domain.models import MessageSource
from jewelai_parser import CandidateClassification, StructuredTarget, parse_full_message
from jewelai_persistence import NotFoundError
from jewelai_prompts import CanonicalInternalFinalPrompt as InternalFinalPrompt
from test_effective_readiness import (  # noqa: F401
    _answer,
    _assert_current_ready,
    _correct,
    ready_session,
)
from test_persistence import build_service
from test_prompt_enrichment_http import _client, _message
from test_prompt_enrichment_runtime import _runtime

from jewelai_api.parsed_enrichment import _json_value
from jewelai_api.prompt_enrichment_runtime import PromptEnrichmentRuntimeService

STYLE_INPUTS = (
    "Design a minimalist engagement ring.",
    "Gold engagement ring with an oval diamond and a minimalist style.",
    "I prefer a minimalist style.",
    "Keep the oval center stone and make the overall design minimalist.",
    "Minimalist gold ring. Do not add a halo.",
    "Make the design minimalist.",
    "Хочу минималистичное кольцо.",
    "Хочу minimalist engagement ring без гало.",
    "Keep the center stone exactly as specified. Do not change its dimensions. "
    "Use a refined, minimalist appearance.",
)


@pytest.fixture
def style_session(engine, tmp_path, request):
    with ExitStack() as stack:

        def create(route="corrections", role="retail_client", locale="en"):
            if route == "corrections":
                return request.getfixturevalue("ready_session")(role, locale)
            service = build_service(engine)
            runtime, store, active, report = _runtime(service, tmp_path / str(uuid4()))
            client, provider = _client(engine, runtime)
            stack.enter_context(client)
            org, _, session = create_hierarchy(client, role_id=role, locale=locale)
            return SimpleNamespace(
                service=service,
                runtime=runtime,
                store=store,
                active=active,
                report=report,
                client=client,
                provider=provider,
                sid=session.json()["session_id"],
                org=org,
                headers={"X-Organization-ID": org},
            )

        yield create


def _history(ctx):
    repo = ctx.service.repository
    try:
        cycles = repo.list_enrichment_cycles(UUID(ctx.sid), UUID(ctx.org))
    except NotFoundError:
        cycles = ()  # A fresh initial session has no release pin or cycles yet.
    return {
        "revisions": [
            v.model_dump(mode="json") for v in repo.list_revisions(UUID(ctx.sid), UUID(ctx.org))
        ],
        "cycles": [
            {"id": str(v.enrichment_cycle_id), "result": v.result.model_dump(mode="json")}
            for v in cycles
        ],
    }


def _submit(ctx, text, route="corrections", **overrides):
    message = _message(ctx.client, ctx.sid, ctx.org, text)
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    payload = {
        "message_id": message["message_id"],
        "expected_revision_id": str(current.revision_id),
        **overrides,
    }
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/{route}",
        headers=ctx.headers,
        json=payload,
    )
    return response, payload, current, message


@pytest.mark.parametrize("text", STYLE_INPUTS)
@pytest.mark.parametrize("route", ("initial", "corrections"))
@pytest.mark.parametrize("role", ("retail_client", "jewelry_designer"))
def test_minimalist_wording_http(style_session, text, route, role, request):
    locale = "ru" if text.startswith("Хочу") else "en"
    ctx = style_session(route, role, locale)
    before = _history(ctx)
    response, payload, current, message = _submit(ctx, text, route)
    after = _history(ctx)
    request.node.user_properties.append(
        (
            "http_evidence",
            {
                "text": text,
                "role": role,
                "locale": locale,
                "route": route,
                "request": payload,
                "response": response.json(),
                "http_status": response.status_code,
                "before": before,
                "after": after,
            },
        )
    )
    if response.status_code == 422:
        assert after == before  # An internal validation failure must not commit a partial cycle.
    assert response.status_code == (201 if route == "initial" else 200), response.json()
    parsed = parse_full_message(
        text,
        locale=locale,
        dictionary=ctx.service.artifacts.dictionary,
        knowledge_runtime=ctx.runtime._load_release().compiled_runtime,
    )
    evaluated = ctx.runtime._evaluate(
        current, parsed, MessageSource(message_id=message["message_id"], recorded_at=NOW)
    )
    assert parsed.original_text == text
    for candidate in parsed.candidates:
        assert text[candidate.evidence.start : candidate.evidence.end] == candidate.evidence.text
    assert len({c.candidate_id for c in parsed.candidates}) == len(parsed.candidates)
    accepted = evaluated.parser_proposal.accepted_updates
    assert len({a.concrete_target for a in accepted}) == len(accepted)
    actual = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    assert actual.design == evaluated.parser_proposal.proposed_design
    style = [d for d in evaluated.dispositions if d.candidate.target == StructuredTarget.STYLE]
    if text == "I prefer a minimalist style.":
        assert style and all(
            d.candidate.classification == CandidateClassification.PREFERENCE for d in style
        )
        assert actual.design.style == current.design.style
        assert all(d.reason.value == "preference_requires_acceptance" for d in style)
    elif any(a.concrete_target == "style" for a in accepted):
        assert actual.design.style.value == ("minimalist",)
        assert not actual.design.style.confirmed and not actual.design.style.locked
        assert actual.design.style.source.message_id == message["message_id"]
        assert all(
            d.enrichment_proposal.value == ["minimalist"] for d in style if d.enrichment_proposal
        )
    state = ctx.runtime.get_current_state(UUID(ctx.sid), UUID(ctx.org))
    assert len(after["cycles"]) == len(before["cycles"]) + 1
    assert after["cycles"][:-1] == before["cycles"]
    assert state.clarification_plan.role_id == role and state.clarification_plan.locale == locale
    assert state.final_output is not None
    prompt = state.final_output.internal_final_prompt
    assert InternalFinalPrompt.model_validate_json(prompt.model_dump_json()) == prompt
    if "Do not add a halo" in text:
        halo = [c for c in prompt.constraints if c.target == "feature.halo"]
        assert len(halo) == 1 and halo[0].kind == "prohibition"
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
    assert ctx.provider.calls == []


@pytest.mark.parametrize(
    "value, expected",
    [
        (("minimalist",), ["minimalist"]),
        (("minimalist", ("halo_style",)), ["minimalist", ["halo_style"]]),
        ("minimalist", "minimalist"),
    ],
)
def test_parser_value_conversion_is_json_compatible(value, expected):
    assert _json_value(value) == expected


def test_style_correction_replay_scope_stale_and_later_clarification(style_session):
    ctx = style_session()
    response, payload, _, _ = _submit(ctx, "Make the design minimalist.")
    assert response.status_code == 200, response.json()
    history = _history(ctx)
    replay = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections", headers=ctx.headers, json=payload
    )
    # The persisted HTTP wrapper rejects a replay against the now-advanced cycle.
    assert replay.status_code == 409
    assert replay.json()["error"] in {"correction_conflict", "stale_revision"}
    assert _history(ctx) == history
    stale, *_ = _submit(
        ctx, "Make the design minimalist.", expected_revision_id=payload["expected_revision_id"]
    )
    assert stale.status_code == 409 and _history(ctx) == history
    foreign = ctx.client.post("/organizations", json={"name": "Foreign style test"}).json()[
        "organization_id"
    ]
    scope = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
        headers={"X-Organization-ID": foreign},
        json=payload,
    )
    assert scope.status_code == 404 and _history(ctx) == history
    unauth = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
        headers={**ctx.headers, "Authorization": ""},
        json=payload,
    )
    assert unauth.status_code == 401 and _history(ctx) == history
    _, state = _correct(ctx, "I prefer yellow.")
    assert any(q.target.value == "metal.color" for q in state.clarification_plan.questions)
    _, state = _answer(ctx, "metal.color")
    _assert_current_ready(ctx, state)
    assert ctx.service.repository.get_current_revision(
        UUID(ctx.sid), UUID(ctx.org)
    ).design.style.value == ("minimalist",)


@pytest.mark.parametrize("route", ("initial", "corrections"))
@pytest.mark.parametrize(
    "invalid",
    (
        {"message_id": "not-a-uuid"},
        {"message_id": []},
        {"expected_revision_id": "bad"},
        {"provenance": "forged"},
        {"decision": "ACCEPT"},
    ),
)
def test_style_fix_does_not_relax_request_validation(style_session, route, invalid):
    ctx = style_session(route)
    before = _history(ctx)
    response, *_ = _submit(ctx, "Make the design minimalist.", route, **invalid)
    assert response.status_code == 422 and _history(ctx) == before


def test_unrecognized_style_preserves_existing_facts_and_text(style_session):
    ctx = style_session()
    response, _, current, message = _submit(ctx, "Use an ultrazigzag appearance.")
    assert response.status_code == 200, response.json()
    actual = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    assert actual == current
    saved = ctx.service.repository.get_message(
        UUID(ctx.sid), UUID(message["message_id"]), UUID(ctx.org)
    )
    assert saved.content == "Use an ultrazigzag appearance."
    from jewelai_api.durable_enrichment import list_user_correction_results

    decision = next(
        d
        for d in list_user_correction_results(
            ctx.service.repository, session_id=UUID(ctx.sid), organization_id=UUID(ctx.org)
        )
        if d.source.message_id == message["message_id"]
    )
    assert decision.parsed_correction.original_text == saved.content
    assert not decision.correction_evaluation.parser_proposal.has_changes


def test_locked_style_and_unrelated_fields_are_not_overwritten(style_session):
    ctx = style_session("initial")
    message = _message(ctx.client, ctx.sid, ctx.org, "Explicit gold material and minimalist style")
    source = {
        "kind": "message",
        "message_id": message["message_id"],
        "recorded_at": NOW.isoformat(),
    }
    current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    design = current.design.model_dump(mode="json")
    state = {
        "availability": "value",
        "origin": "explicit",
        "source": source,
        "confirmed": False,
        "locked": False,
    }
    design["style"] = {**state, "value": ["minimalist"]}
    design["metal"]["material"] = {**state, "value": "gold"}
    response = ctx.client.post(
        f"/sessions/{ctx.sid}/revisions",
        headers=ctx.headers,
        json={
            "action": "edit",
            "expected_revision_id": str(current.revision_id),
            "proposed_design": design,
            "source": source,
            "reason": "Explicit test prerequisites",
        },
    )
    assert response.status_code == 200, response.json()
    for target in ("style", "metal.material"):
        for action in ("confirm", "lock"):
            current = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
            response = ctx.client.post(
                f"/sessions/{ctx.sid}/revisions",
                headers=ctx.headers,
                json={
                    "action": action,
                    "target": target,
                    "expected_revision_id": str(current.revision_id),
                    "source": {
                        "kind": "message",
                        "message_id": message["message_id"],
                        "recorded_at": NOW.isoformat(),
                    },
                    "reason": "Protect explicitly provided synthetic test values",
                },
            )
            assert response.status_code == 200, response.json()
    # Lock before the initial enrichment cycle, so revision/cycle binding remains valid.
    response, *_ = _submit(ctx, "Minimalist gold engagement ring.", "initial")
    assert response.status_code == 201, response.json()
    before = ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org))
    response, *_ = _submit(ctx, "Use a halo style.")
    assert response.status_code == 200, response.json()
    assert response.json()["outcome"] == "REJECTED"
    assert ctx.service.repository.get_current_revision(UUID(ctx.sid), UUID(ctx.org)) == before


def test_minimalist_halo_corrections_preserve_active_and_superseded_evidence(style_session):
    ctx = style_session()
    for text, expected in (
        ("Minimalist engagement ring. Do not add a halo.", "prohibition"),
        ("Minimalist engagement ring. Add a halo.", "requirement"),
        ("Make the design minimalist. Do not add a halo.", "prohibition"),
    ):
        response, *_ = _submit(ctx, text)
        assert response.status_code == 200, response.json()
        state = ctx.runtime.get_current_state(UUID(ctx.sid), UUID(ctx.org))
        active = [
            c
            for c in state.final_output.internal_final_prompt.constraints
            if c.target == "feature.halo"
        ]
        assert len(active) == 1 and active[0].kind == expected
        _assert_current_ready(ctx, state)
