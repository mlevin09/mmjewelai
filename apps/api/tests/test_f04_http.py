"""Real persisted F04 HTTP tests; explicit test-only creation, default app stays L."""

import hashlib
import json
import os
from contextlib import contextmanager
from copy import copy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from conftest import ROOT, create_hierarchy
from test_p010_symmetry_runtime import p010_bundle
from test_prompt_enrichment_composition import _client, _release
from test_prompt_enrichment_http import _message

from jewelai_api.artifacts import load_runtime_artifacts
from jewelai_api.schemas import CreateSessionRequest
from jewelai_api.settings import ArtifactVersions


@contextmanager
def f04_session(engine, tmp_path, *, binding=False, locale="en", role_id="retail_client"):
    config, _, _ = _release(tmp_path, bundle=p010_bundle() if binding else None)
    client, app, provider = _client(engine, config)
    runtime = app.state.prompt_enrichment_service
    trace = []

    def record(response):
        response.read()
        try:
            body = response.json()
        except ValueError:
            return
        request = response.request
        trace.append(
            dict(
                method=request.method,
                path=request.url.path,
                request=json.loads(request.content) if request.content else None,
                status=response.status_code,
                response=body,
            )
        )

    client.event_hooks["response"].append(record)
    with client:
        org, project, legacy = create_hierarchy(client, locale=locale, role_id=role_id)
        assert legacy.status_code == 201
        # The approved test-only server control creates a new F row; it does not
        # upgrade a legacy session or expose a client-controlled profile field.
        creator = copy(app.state.service)
        creator.artifacts = load_runtime_artifacts(
            ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0")
        )
        session = creator.create_session(
            UUID(project), UUID(org), CreateSessionRequest(role_id=role_id, locale=locale)
        )
        sid = session.session_id
        headers = {"X-Organization-ID": org}
        try:
            yield SimpleNamespace(
                client=client,
                app=app,
                runtime=runtime,
                repo=runtime.repository,
                sid=sid,
                org=UUID(org),
                headers=headers,
                config=config,
                provider=provider,
                legacy=legacy.json(),
            )
        finally:
            destination = os.getenv("F04_EVIDENCE_DIR")
            if destination:
                root = Path(destination)
                root.mkdir(parents=True, exist_ok=True)
                payload = dict(
                    test=os.getenv("PYTEST_CURRENT_TEST", "supplemental"),
                    backend=engine.dialect.name,
                    session_id=str(sid),
                    provider_calls=len(provider.calls),
                    http=trace,
                )
                repo = runtime.repository
                persisted = repo.get_design_session(sid, UUID(org))
                payload["revisions"] = [
                    r.model_dump(mode="json") for r in repo.list_revisions(sid, UUID(org))
                ]
                if persisted.knowledge_package_id is not None:
                    payload["cycles"] = [
                        dict(
                            cycle_id=str(c.enrichment_cycle_id),
                            cycle_number=c.cycle_number,
                            revision_id=str(c.specification_revision_id),
                            result=c.result.model_dump(mode="json"),
                        )
                        for c in repo.list_enrichment_cycles(sid, UUID(org))
                    ]
                    payload["plans"] = [
                        p.plan_payload for p in repo.list_clarification_plans(sid, UUID(org))
                    ]
                    payload["answers"] = [
                        a.result_payload for a in repo.list_clarification_answers(sid, UUID(org))
                    ]
                    payload["corrections"] = [
                        c.result_payload for c in repo.list_user_corrections(sid, UUID(org))
                    ]
                    # Supplemental source reparse is labelled separately; it is not
                    # claimed to be an HTTP response or a second canonical write.
                    from jewelai_domain.clarification_state import evidence_hash
                    from jewelai_parser import parse_full_message

                    bound = runtime._for_session(sid, UUID(org))
                    verified = bound._load_release()
                    sources = {p["trigger"]["message_id"] for p in payload["plans"]}
                    payload["supplemental_reparsed_sources"] = []
                    for mid in sorted(sources):
                        message = repo.get_message(sid, UUID(mid), UUID(org))
                        parsed = parse_full_message(
                            message.content,
                            locale=locale,
                            dictionary=bound.artifacts.dictionary,
                            knowledge_runtime=verified.compiled_runtime,
                        )
                        payload["supplemental_reparsed_sources"].append(
                            dict(
                                message_id=mid,
                                source_sha256=hashlib.sha256(message.content.encode()).hexdigest(),
                                parse_result=parsed.model_dump(mode="json"),
                                parse_sha256=evidence_hash(parsed),
                            )
                        )
                raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()
                (root / (hashlib.sha256(raw).hexdigest() + ".json")).write_bytes(raw)


def initial(ctx, text):
    revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/initial",
        headers=ctx.headers,
        json={
            "schema_version": "2.0.0",
            "expected_revision_id": str(revision.revision_id),
            "message_id": message["message_id"],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def answer(ctx, state, decision="SELECT_OPTION", value="gold", *, request=None):
    question = next(
        q for q in state["clarification_questions"] if q["semantic_question_id"] == "METAL_MATERIAL"
    )
    option = (
        next(o for o in question["options"] if o["value"] == value)
        if decision == "SELECT_OPTION"
        else None
    )
    message = _message(
        ctx.client, str(ctx.sid), str(ctx.org), "Synthetic explicit clarification decision."
    )
    payload = request or dict(
        schema_version="2.0.0",
        clarification_plan_id=state["clarification_plan_id"],
        plan_content_hash=state["clarification_plan_content_hash"],
        clarification_id=question["clarification_id"],
        decision=decision,
        selected_option=option["value"] if option else None,
        selected_option_id=option["option_id"] if option else None,
        expected_revision_id=state["authoritative_revision_id"],
        answer_id=str(uuid4()),
        message_id=message["message_id"],
    )
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
        headers=ctx.headers,
        json=payload,
    )
    return response, payload


def correct(ctx, state, text):
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    latest = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1]
    payload = dict(
        schema_version="2.0.0",
        expected_revision_id=state["authoritative_revision_id"],
        message_id=message["message_id"],
        expected_enrichment_cycle_id=state["enrichment_cycle_id"],
        expected_enrichment_result_hash=latest.result.content_hash,
        expected_clarification_plan_hash=state["clarification_plan_content_hash"],
    )
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections", headers=ctx.headers, json=payload
    )
    assert response.status_code == 200, response.json()
    return response.json()["state"]


@pytest.mark.parametrize(
    "text", ["Gold or platinum ring with an oval diamond.", "Gold and platinum ring."]
)
def test_f04_material_select_is_persisted_http(engine, tmp_path, text):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, text)
        assert state["schema_version"] == "2.0.0"
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert before.design.metal.material is None
        response, payload = answer(ctx, state)
        assert response.status_code == 200, response.json()
        after = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert after.design.metal.material.value == "gold"
        assert after.design.metal.material.source.message_id == payload["message_id"]
        assert after.design.center_stone == before.design.center_stone
        assert not after.design.metal.material.confirmed and not after.design.metal.material.locked
        assert not any(
            c["availability_target_ref"]["concrete_target"] == "metal.material"
            for c in response.json()["state"]["current_unresolved_causal_summaries"]
        )
        assert ctx.provider.calls == []


@pytest.mark.parametrize("decision", ["SKIP", "UNKNOWN"])
def test_f04_material_unanswered_is_dormant_http(engine, tmp_path, decision):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, "Gold or platinum ring with an oval diamond.")
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        response, _ = answer(ctx, state, decision)
        assert response.status_code == 200, response.json()
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
        state = response.json()["state"]
        causes = [
            c
            for c in state["current_unresolved_causal_summaries"]
            if c["availability_target_ref"]["concrete_target"] == "metal.material"
        ]
        assert (
            len(causes) == 1
            and causes[0]["status"] == "OPEN"
            and causes[0]["offer_state"] == "DORMANT"
        )
        assert not any(
            q["semantic_question_id"] == "METAL_MATERIAL" for q in state["clarification_questions"]
        )


def test_f04_equivalence_is_persisted_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, "A gold ring with gold metal.")
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material.value == "gold"
        assert not any(
            q["semantic_question_id"] == "METAL_MATERIAL" for q in state["clarification_questions"]
        )
        plans = ctx.repo.list_clarification_plans(ctx.sid, ctx.org)
        conflicts = plans[0].plan_payload["conflicts"]
        assert (
            len(conflicts) == 1
            and conflicts[0]["kind"] == "equivalent"
            and len(conflicts[0]["occurrences"]) == 2
        )


@pytest.mark.parametrize("decision", ["SKIP", "UNKNOWN"])
def test_f04_skipped_cause_resolved_by_actual_correction_http(engine, tmp_path, decision):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, "Gold or platinum ring with an oval diamond.")
        response, _ = answer(ctx, state, decision)
        assert response.status_code == 200, response.json()
        state = response.json()["state"]
        old = ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0]
        state = correct(ctx, state, "A platinum ring.")
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material.value
            == "platinum"
        )
        assert (
            ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0].result_payload
            == old.result_payload
        )
        assert old.result_payload["blocks_progression"] is True
        assert not any(
            c["availability_target_ref"]["concrete_target"] == "metal.material"
            for c in state["current_unresolved_causal_summaries"]
        )
        plan = ctx.repo.get_clarification_plan(
            ctx.sid, UUID(state["clarification_plan_id"]), ctx.org
        ).plan_payload
        material = [
            c
            for c in plan["frontier_core"]["cause_states"]
            if c["availability_target_ref"]["concrete_target"] == "metal.material"
        ]
        assert material[0]["status"] == "RESOLVED" and material[0]["resolution_ref"] is not None


def test_f04_unrelated_uncertain_correction_cannot_discharge_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, "Gold or platinum ring with an oval diamond.")
        response, _ = answer(ctx, state, "SKIP")
        state = response.json()["state"]
        for text in ("White metal.", "Perhaps platinum."):
            state = correct(ctx, state, text)
            material = [
                c
                for c in state["current_unresolved_causal_summaries"]
                if c["availability_target_ref"]["concrete_target"] == "metal.material"
            ]
            assert (
                len(material) == 1
                and material[0]["status"] == "OPEN"
                and material[0]["offer_state"] == "DORMANT"
            )
            assert ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material is None


def resume(ctx, state, cause_id, *, payload=None):
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), "Synthetic explicit resume.")
    latest = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)[-1]
    request = payload or dict(
        schema_version="1.0.0",
        request_id=str(uuid4()),
        message_id=message["message_id"],
        expected_revision_id=state["authoritative_revision_id"],
        expected_enrichment_cycle_id=state["enrichment_cycle_id"],
        expected_enrichment_result_hash=latest.result.content_hash,
        expected_clarification_plan_hash=state["clarification_plan_content_hash"],
    )
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarifications/{cause_id}/resume",
        headers=ctx.headers,
        json=request,
    )
    return response, request


def test_f04_explicit_resume_is_persisted_idempotent_and_revision_neutral(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, "Gold or platinum ring with an oval diamond.")
        old_question = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "METAL_MATERIAL"
        )
        response, _ = answer(ctx, state, "UNKNOWN")
        state = response.json()["state"]
        revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        response, payload = resume(ctx, state, old_question["cause_id"])
        assert response.status_code == 200, response.json()
        new = response.json()
        question = next(
            q
            for q in new["state"]["clarification_questions"]
            if q["semantic_question_id"] == "METAL_MATERIAL"
        )
        assert (
            question["clarification_id"] != old_question["clarification_id"]
            and question["offer_ordinal"] == 1
        )
        assert question["cause_id"] == old_question["cause_id"]
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == revision
        count = len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org))
        replay, _ = resume(ctx, new["state"], old_question["cause_id"], payload=payload)
        assert replay.status_code == 200 and replay.json()["result"] == new["result"]
        assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == count
        altered = {
            **payload,
            "message_id": _message(
                ctx.client, str(ctx.sid), str(ctx.org), "A different resume intent."
            )["message_id"],
        }
        conflict, _ = resume(ctx, new["state"], old_question["cause_id"], payload=altered)
        assert conflict.status_code == 409


def test_f04_history_does_not_block_ifp3_or_preparation2_after_causal_resolution(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(
            ctx,
            "Gold or platinum ring with an oval diamond center stone. White metal. "
            "Center stone in prong setting. Center stone 9 x 7 x 4 mm.",
        )
        response, _ = answer(ctx, state, "SKIP")
        state = response.json()["state"]
        assert state["can_prepare"] is False
        state = correct(ctx, state, "A platinum ring.")
        assert state["internal_final_prompt_readiness"] in {"ready", "ready_with_unresolved"}
        assert state["can_prepare"] is True
        final = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert final.status_code == 200, final.json()
        body = final.json()
        assert (
            body["schema_version"] == "3.0.0" and body["description"]["schema_version"] == "2.0.0"
        )
        prompt = body["internal_final_prompt"]
        assert any(d["blocks_progression"] for d in prompt["decision_lineage"])
        assert not any(u["blocking"] for u in prompt["unresolved_details"])
        key = str(uuid4())
        headers = {**ctx.headers, "Idempotency-Key": key}
        prepared = ctx.client.post(
            f"/sessions/{ctx.sid}/generation-preparations",
            headers=headers,
            json=state["preparation_expectations"],
        )
        assert prepared.status_code == 201, prepared.json()
        assert prepared.json()["schema_version"] == "2.0.0"
        again = ctx.client.post(
            f"/sessions/{ctx.sid}/generation-preparations",
            headers=headers,
            json=state["preparation_expectations"],
        )
        assert again.status_code == 200 and again.json() == prepared.json()
        fetched = ctx.client.get(
            f"/sessions/{ctx.sid}/generation-preparations/{prepared.json()['preparation_id']}",
            headers=ctx.headers,
        )
        assert fetched.status_code == 200 and fetched.json() == prepared.json()
        assert ctx.provider.calls == []


READY_TEXT = (
    "Gold or platinum ring with an oval diamond center stone. White metal. "
    "Center stone in prong setting. Center stone 9 x 7 x 4 mm."
)


def state_get(ctx):
    result = ctx.client.get(f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers)
    assert result.status_code == 200, result.json()
    return result.json()


def restart(ctx, engine):
    client, app, provider = _client(engine, ctx.config)
    client.event_hooks["response"].extend(ctx.client.event_hooks["response"])
    ctx.client = client
    ctx.app = app
    ctx.runtime = app.state.prompt_enrichment_service
    ctx.repo = ctx.runtime.repository
    ctx.provider = provider
    return client


@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "Gold or platinum ring."),
        ("ru", "Кольцо из золота или платины."),
    ],
)
@pytest.mark.parametrize(
    "role_id",
    [
        "retail_client",
        "sales_manager",
        "buyer",
        "marketing",
        "jewelry_designer",
        "industrial_designer",
    ],
)
def test_f04_exact_role_locale_question_http(engine, tmp_path, locale, text, role_id):
    with f04_session(engine, tmp_path, locale=locale, role_id=role_id) as ctx:
        state = initial(ctx, text)
        q = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "METAL_MATERIAL"
        )
        artifacts = load_runtime_artifacts(ROOT, ArtifactVersions(questions="2.0.0", rules="2.0.0"))
        expected = artifacts.questions.render("METAL_MATERIAL", role_id, locale).wording
        assert q["text"] == expected.format(
            options=(" или " if locale == "ru" else " or ").join(o["label"] for o in q["options"])
        )
        assert q["allowed_decisions"] == ["SELECT_OPTION", "SKIP", "UNKNOWN"]


@pytest.mark.parametrize(
    "text,locale,material",
    [
        ("Кольцо из золота и gold metal.", "ru", "gold"),
        ("Gold or платина ring.", "en", None),
        ("No gold or platinum ring.", "en", None),
        ("Perhaps gold or platinum ring.", "en", None),
        ("Хочу золото или платину.", "ru", None),
        ("Gold prongs and platinum ring.", "en", "platinum"),
        ("Кольцо, без гало, золота или платины.", "ru", None),
    ],
)
@pytest.mark.parametrize("binding", [False, True])
def test_f04_source_authority_and_component_controls_http(
    engine, tmp_path, text, locale, material, binding
):
    with f04_session(engine, tmp_path, locale=locale, binding=binding) as ctx:
        state = initial(ctx, text)
        revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert getattr(revision.design.metal.material, "value", None) == material
        if text not in {"Gold or платина ring."}:
            assert not any(
                q["semantic_question_id"] == "METAL_MATERIAL"
                for q in state["clarification_questions"]
            )
        assert ctx.provider.calls == []


@pytest.mark.parametrize(
    "mutation,status",
    [
        ({"decision": "ACCEPT"}, 422),
        ({"decision": "REJECT"}, 422),
        ({"selected_option_id": "option_" + "0" * 64}, 422),
        ({"selected_option": "platinum"}, 422),
        ({"plan_content_hash": "0" * 64}, 409),
        ({"expected_revision_id": str(uuid4())}, 409),
    ],
)
def test_f04_invalid_material_decision_is_atomic_http(engine, tmp_path, mutation, status):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, "Gold or platinum ring.")
        q = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "METAL_MATERIAL"
        )
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Synthetic invalid decision.")
        payload = dict(
            schema_version="2.0.0",
            clarification_plan_id=state["clarification_plan_id"],
            plan_content_hash=state["clarification_plan_content_hash"],
            clarification_id=q["clarification_id"],
            decision="SELECT_OPTION",
            selected_option="gold",
            selected_option_id=q["options"][0]["option_id"],
            expected_revision_id=state["authoritative_revision_id"],
            answer_id=str(uuid4()),
            message_id=msg["message_id"],
        )
        payload.update(mutation)
        if payload["decision"] != "SELECT_OPTION":
            payload.update(selected_option=None, selected_option_id=None)
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        response, _ = answer(ctx, state, request=payload)
        assert response.status_code == status, response.json()
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
        assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == 1
        assert ctx.repo.list_clarification_answers(ctx.sid, ctx.org) == ()


def test_f04_answer_replay_stale_and_restart_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        response, payload = answer(ctx, state)
        assert response.status_code == 200, response.json()
        accepted = response.json()
        count = len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org))
        with restart(ctx, engine):
            assert state_get(ctx) == accepted["state"]
            replay, _ = answer(ctx, state, request={**payload, "answer_id": str(uuid4())})
            assert replay.status_code == 200, replay.json()
            assert replay.json()["answer_content_hash"] == accepted["answer_content_hash"]
            assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == count
            conflict, _ = answer(
                ctx,
                state,
                request={
                    **payload,
                    "selected_option": "platinum",
                    "selected_option_id": next(
                        o["option_id"]
                        for q in state["clarification_questions"]
                        if q["semantic_question_id"] == "METAL_MATERIAL"
                        for o in q["options"]
                        if o["value"] == "platinum"
                    ),
                },
            )
            assert conflict.status_code == 409, conflict.json()
            assert (
                ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material.value
                == "gold"
            )


@pytest.mark.parametrize("version", [None, "1.0.0", "3.0.0"])
def test_f04_request_version_rejected_without_append_http(engine, tmp_path, version):
    with f04_session(engine, tmp_path) as ctx:
        rev = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Gold ring.")
        request = dict(expected_revision_id=str(rev.revision_id), message_id=msg["message_id"])
        if version is not None:
            request["schema_version"] = version
        result = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/initial", headers=ctx.headers, json=request
        )
        assert result.status_code in {409, 422}, result.json()
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == rev
        assert ctx.repo.get_design_session(ctx.sid, ctx.org).knowledge_package_id is None


@pytest.mark.parametrize("decision", ["SKIP", "UNKNOWN"])
def test_f04_optional_offer_unanswered_is_nonblocking_http(engine, tmp_path, decision):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(
            ctx,
            "A ring with an oval diamond center stone in prong setting. "
            "Center stone 9 x 7 x 4 mm. I would prefer white metal.",
        )
        optional = [
            q for q in state["clarification_questions"] if q["category"] == "preference_acceptance"
        ]
        assert optional, state["clarification_questions"]
        q = optional[0]
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "Synthetic optional decision.")
        payload = dict(
            schema_version="2.0.0",
            clarification_plan_id=state["clarification_plan_id"],
            plan_content_hash=state["clarification_plan_content_hash"],
            clarification_id=q["clarification_id"],
            decision=decision,
            selected_option=None,
            selected_option_id=None,
            expected_revision_id=state["authoritative_revision_id"],
            answer_id=str(uuid4()),
            message_id=msg["message_id"],
        )
        response = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json=payload,
        )
        assert response.status_code == 200, response.json()
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
        cause = next(
            c
            for c in response.json()["state"]["current_unresolved_causal_summaries"]
            if c["cause_id"] == q["cause_id"]
        )
        assert cause["criticality"] == "NONBLOCKING" and cause["offer_state"] == "DORMANT"
        assert not ctx.repo.list_clarification_answers(ctx.sid, ctx.org)[0].result_payload[
            "blocks_progression"
        ]


def test_f04_three_cycle_persisted_restoration_and_preparation_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        answered, _ = answer(ctx, state, "UNKNOWN")
        assert answered.status_code == 200, answered.json()
        state = correct(ctx, answered.json()["state"], "A platinum ring.")
        before = state_get(ctx)
        cycles = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)
        assert len(cycles) == 3
        with restart(ctx, engine):
            assert state_get(ctx) == before
            prepared = ctx.client.post(
                f"/sessions/{ctx.sid}/generation-preparations",
                headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
                json=before["preparation_expectations"],
            )
            assert prepared.status_code == 201, prepared.json()
            again = state_get(ctx)
            assert again == before
            result = ctx.client.get(
                f"/sessions/{ctx.sid}/generation-preparations/{prepared.json()['preparation_id']}",
                headers=ctx.headers,
            )
            assert result.status_code == 200 and result.json() == prepared.json()


def answer_question(ctx, state, question, decision):
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), "Synthetic explicit decision.")
    payload = dict(
        schema_version="2.0.0",
        clarification_plan_id=state["clarification_plan_id"],
        plan_content_hash=state["clarification_plan_content_hash"],
        clarification_id=question["clarification_id"],
        decision=decision,
        selected_option=None,
        selected_option_id=None,
        expected_revision_id=state["authoritative_revision_id"],
        answer_id=str(uuid4()),
        message_id=message["message_id"],
    )
    return ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
        headers=ctx.headers,
        json=payload,
    )


@pytest.mark.parametrize("decision", ["SKIP", "UNKNOWN"])
def test_f04_ready_optional_frontier_stays_nonblocking_http(engine, tmp_path, decision):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        response, _ = answer(ctx, state)
        assert response.status_code == 200, response.json()
        state = correct(ctx, response.json()["state"], "I prefer yellow metal.")
        assert state["can_prepare"] is True
        q = next(
            q for q in state["clarification_questions"] if q["category"] == "preference_acceptance"
        )
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        result = answer_question(ctx, state, q, decision)
        assert result.status_code == 200, result.json()
        assert result.json()["state"]["can_prepare"] is True
        assert result.json()["state"]["internal_final_prompt_readiness"] == "ready_with_unresolved"
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
        with restart(ctx, engine):
            assert state_get(ctx) == result.json()["state"]


def test_f04_relevant_dependency_reoffers_once_not_unrelated_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(
            ctx, "A white gold ring with an oval diamond center stone in prong setting."
        )
        q = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_DIMENSIONS"
        )
        response = answer_question(ctx, state, q, "UNKNOWN")
        assert response.status_code == 200, response.json()
        state = response.json()["state"]
        assert not any(x["cause_id"] == q["cause_id"] for x in state["clarification_questions"])
        state = correct(ctx, state, "A platinum ring.")
        assert not any(x["cause_id"] == q["cause_id"] for x in state["clarification_questions"])
        state = correct(ctx, state, "An emerald center stone.")
        new = next(x for x in state["clarification_questions"] if x["cause_id"] == q["cause_id"])
        assert new["offer_trigger"] == "relevant_change" and new["offer_ordinal"] == 1
        response = answer_question(ctx, state, new, "SKIP")
        assert response.status_code == 200, response.json()
        state = correct(ctx, response.json()["state"], "An emerald center stone.")
        assert not any(x["cause_id"] == q["cause_id"] for x in state["clarification_questions"])
        with restart(ctx, engine):
            assert state_get(ctx) == state


@pytest.mark.parametrize("protection", ["confirmed", "locked"])
@pytest.mark.parametrize("schema", ["1.0.0", "1.1.0"])
def test_f04_protected_material_cannot_be_overwritten_http(engine, tmp_path, protection, schema):
    from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1
    from jewelai_domain.revisions import lock_field
    from test_core_intent import _seed

    with f04_session(engine, tmp_path) as ctx:
        before = _seed(ctx, material=True)
        if protection == "locked":
            locked = lock_field(
                before,
                "metal.material",
                expected_revision_id=before.revision_id,
                source=before.design.metal.material.source,
                reason="Synthetic lock",
                created_at=before.created_at,
            )
            ctx.repo.append_revision_cas(ctx.sid, ctx.org, before.revision_id, locked)
            before = locked
        if schema == "1.1.0":
            migrated = migrate_design_revision_v1_to_v1_1(
                before,
                revision_id=uuid4(),
                created_at=before.created_at,
                source=before.design.metal.material.source,
                reason="Synthetic authorized schema upgrade",
            )
            ctx.repo.upgrade_design_session_schema_v1_1(
                ctx.sid, ctx.org, before.revision_id, migrated
            )
            before = migrated
        state = initial(ctx, READY_TEXT)
        assert (
            ctx.repo.get_current_revision(ctx.sid, ctx.org).design.metal.material
            == before.design.metal.material
        )
        assert not any(
            q["semantic_question_id"] == "METAL_MATERIAL" for q in state["clarification_questions"]
        )
        assert state["can_prepare"] is True
        protected_cause = next(
            c
            for c in state["current_unresolved_causal_summaries"]
            if c["availability_target_ref"]["concrete_target"] == "metal.material"
        )
        assert protected_cause["criticality"] == "NONBLOCKING"
        state = correct(ctx, state, "A platinum ring.")
        current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        if protection == "confirmed":
            # Existing explicit correction authority may replace confirmed,
            # unlocked facts; F does not invent stronger cancellation rules.
            assert current.design.metal.material.value == "platinum"
            assert not any(
                c["availability_target_ref"]["concrete_target"] == "metal.material"
                for c in state["current_unresolved_causal_summaries"]
            )
            with restart(ctx, engine):
                assert state_get(ctx) == state
            return
        assert current.design.metal.material == before.design.metal.material
        cause = next(
            c
            for c in state["current_unresolved_causal_summaries"]
            if c["availability_target_ref"]["concrete_target"] == "metal.material"
        )
        assert cause["status"] == "OPEN" and cause["offer_state"] == "PROTECTED"
        result, _ = resume(ctx, state, cause["cause_id"])
        assert result.status_code == 409, result.json()
        with restart(ctx, engine):
            assert state_get(ctx) == state


def test_f04_scope_and_closed_resume_do_not_append_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        q = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "METAL_MATERIAL"
        )
        answered, _ = answer(ctx, state)
        assert answered.status_code == 200
        state = answered.json()["state"]
        count = len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org))
        closed, _ = resume(ctx, state, q["cause_id"])
        assert closed.status_code == 409, closed.json()
        ctx.client.headers["Authorization"] = "Bearer test-owner-b"
        org, _, _ = create_hierarchy(ctx.client)
        response = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers={"X-Organization-ID": org}
        )
        assert response.status_code == 404, response.json()
        ctx.client.headers["Authorization"] = "Bearer test-owner-a"
        assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == count


@pytest.mark.parametrize("mutation", ["uppercase_uuid", "missing_version", "extra_authority"])
def test_f04_strict_wire_rejects_normalization_or_authority_http(engine, tmp_path, mutation):
    with f04_session(engine, tmp_path) as ctx:
        rev = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(ctx.client, str(ctx.sid), str(ctx.org), "A gold ring.")
        request = dict(
            schema_version="2.0.0",
            expected_revision_id=str(rev.revision_id),
            message_id=msg["message_id"],
        )
        if mutation == "uppercase_uuid":
            request["expected_revision_id"] = request["expected_revision_id"].upper()
        elif mutation == "missing_version":
            del request["schema_version"]
        else:
            request["frontier_core"] = {"cause_states": []}
        response = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/initial", headers=ctx.headers, json=request
        )
        assert response.status_code in {409, 422}, response.json()
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == rev
        assert ctx.repo.get_design_session(ctx.sid, ctx.org).knowledge_package_id is None


def test_f04_duplicate_json_keys_are_rejected_without_append_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        revision = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        message = _message(ctx.client, str(ctx.sid), str(ctx.org), "A gold ring.")
        raw = (
            '{"schema_version":"2.0.0","expected_revision_id":"'
            + str(revision.revision_id)
            + '","message_id":"'
            + message["message_id"]
            + '","message_id":"'
            + message["message_id"]
            + '"}'
        )
        response = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/initial",
            headers={**ctx.headers, "Content-Type": "application/json"},
            content=raw,
        )
        assert response.status_code == 422, response.json()
        assert ctx.repo.get_design_session(ctx.sid, ctx.org).knowledge_package_id is None
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == revision


def test_f04_answer_fault_rolls_back_revision_cycle_and_decision(engine, tmp_path, monkeypatch):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)

        def failed(*args, **kwargs):
            raise RuntimeError("Synthetic transaction fault after provisional canonical write")

        monkeypatch.setattr(ctx.repo, "_add_clarification_plan", failed)
        response, _ = answer(ctx, state)
        assert response.status_code == 500
        assert ctx.repo.get_current_revision(ctx.sid, ctx.org) == before
        assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == 1
        assert not ctx.repo.list_clarification_answers(ctx.sid, ctx.org)
        assert len(ctx.repo.list_clarification_plans(ctx.sid, ctx.org)) == 1


def test_f04_resume_stale_plan_after_revision_neutral_answer_http(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(
            ctx, "A white gold ring with an oval diamond center stone in prong setting."
        )
        question = next(
            q
            for q in state["clarification_questions"]
            if q["semantic_question_id"] == "CENTER_STONE_DIMENSIONS"
        )
        response = answer_question(ctx, state, question, "SKIP")
        assert response.status_code == 200
        state = response.json()["state"]
        resumed, _ = resume(ctx, state, question["cause_id"])
        assert resumed.status_code == 200, resumed.json()
        stale, _ = resume(ctx, state, question["cause_id"])
        assert stale.status_code == 409, stale.json()
        assert len(ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)) == 3


def test_f04_actual_ancestor_lock_preserved_in_schema11_http(engine, tmp_path):
    from conftest import NOW
    from jewelai_domain.models import MessageSource
    from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1
    from jewelai_domain.revisions import confirm_field, lock_field, revise_design

    with f04_session(engine, tmp_path, binding=True) as ctx:
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        msg = _message(
            ctx.client,
            str(ctx.sid),
            str(ctx.org),
            "Synthetic explicit composition and ancestor LOCK.",
        )
        source = MessageSource(message_id=msg["message_id"], recorded_at=NOW)
        migrated = migrate_design_revision_v1_to_v1_1(
            before,
            revision_id=uuid4(),
            created_at=NOW,
            source=source,
            reason="Synthetic schema upgrade",
        )
        ctx.repo.upgrade_design_session_schema_v1_1(ctx.sid, ctx.org, before.revision_id, migrated)
        explicit = dict(
            availability="value",
            origin="explicit",
            source=source.model_dump(mode="json"),
            confirmed=False,
            locked=False,
        )
        design = migrated.design.model_dump(mode="json")
        design["composition"] = {
            **explicit,
            "value": {"symmetry_mode": {**explicit, "value": "asymmetrical"}},
        }
        seeded = revise_design(
            migrated,
            design,
            expected_revision_id=migrated.revision_id,
            source=source,
            reason="Synthetic explicit composition",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, migrated.revision_id, seeded)
        confirmed = confirm_field(
            seeded,
            "composition",
            expected_revision_id=seeded.revision_id,
            source=source,
            reason="Synthetic confirmation",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, seeded.revision_id, confirmed)
        locked = lock_field(
            confirmed,
            "composition",
            expected_revision_id=confirmed.revision_id,
            source=source,
            reason="Synthetic ancestor LOCK",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, confirmed.revision_id, locked)
        state = initial(
            ctx,
            "A white gold ring with an oval diamond center stone in prong setting. "
            "Center stone 9 x 7 x 4 mm.",
        )
        state = correct(ctx, state, "A symmetrical ring.")
        current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert current.design.composition == locked.design.composition
        assert current.design.composition.value.symmetry_mode.value == "asymmetrical"
        with restart(ctx, engine):
            assert state_get(ctx) == state


def test_f04_keep_compatible_corrections_retain_original_evidence_http(engine, tmp_path):
    with f04_session(engine, tmp_path, binding=True, locale="ru") as ctx:
        from conftest import NOW
        from jewelai_domain.models import MessageSource
        from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1

        old = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Synthetic authorized schema upgrade."
        )
        upgraded = migrate_design_revision_v1_to_v1_1(
            old,
            revision_id=uuid4(),
            created_at=NOW,
            source=MessageSource(message_id=message["message_id"], recorded_at=NOW),
            reason="Synthetic schema upgrade",
        )
        ctx.repo.upgrade_design_session_schema_v1_1(ctx.sid, ctx.org, old.revision_id, upgraded)
        state = initial(ctx, "Асимметричное кольцо — не выравнивай его.")
        before = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        original = ctx.repo.get_clarification_plan(
            ctx.sid, UUID(state["clarification_plan_id"]), ctx.org
        ).plan_payload["constraint_evidence"]
        keep = next(e for e in original if e["kind"] == "preservation" and e["status"] == "active")
        for text in ("An asymmetric ring.", "Кольцо из золота.", "An oval diamond center stone."):
            state = correct(ctx, state, text)
            current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
            assert (
                current.design.composition.value.symmetry_mode
                == before.design.composition.value.symmetry_mode
            )
            plan = ctx.repo.get_clarification_plan(
                ctx.sid, UUID(state["clarification_plan_id"]), ctx.org
            ).plan_payload
            preserved = next(
                e for e in plan["constraint_evidence"] if e["evidence_id"] == keep["evidence_id"]
            )
            assert preserved == keep
            with restart(ctx, engine):
                assert state_get(ctx) == state
