"""C1 raw-text observations on the existing TEST-ONLY persisted HTTP boundary."""

import json
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from conftest import NOW, create_hierarchy
from jewelai_domain.dictionary import DictionaryLocale
from jewelai_domain.models import MessageSource
from jewelai_domain.revisions import confirm_field, lock_field, revise_design
from jewelai_parser.p010_symmetry import has_p010_binding
from test_p010_symmetry_runtime import p010_bundle
from test_prompt_enrichment_composition import _client, _release
from test_prompt_enrichment_http import _message

C1_CASES = (
    ("C1-01", "A gold ring is not what I want.", "en", {}),
    (
        "C1-03",
        "An oval diamond ring. No side stones.",
        "en",
        {"center_stone.shape": "oval", "center_stone.material": "diamond"},
    ),
    ("C1-04", "A gold ring. No prongs.", "en", {"metal.material": "gold"}),
    (
        "C1-05",
        "No side stones. An oval diamond center stone.",
        "en",
        {"center_stone.shape": "oval", "center_stone.material": "diamond"},
    ),
    ("C1-06", "I do not want gold. Give me a platinum ring.", "en", {"metal.material": "platinum"}),
    (
        "C1-07",
        "Овальный центральный алмаз. Боковые камни не нужны.",
        "ru",
        {"center_stone.shape": "oval", "center_stone.material": "diamond"},
    ),
    (
        "C1-08",
        "An oval diamond center stone. Боковые камни не нужны.",
        "ru",
        {"center_stone.shape": "oval", "center_stone.material": "diamond"},
    ),
    ("C1-09", "Кольцо из золота. Крапаны не нужны.", "ru", {"metal.material": "gold"}),
    ("C1-10", "Maybe platinum. A ring.", "en", {}),
    ("C1-11", "A ring, no halo, yellow gold or oval diamond.", "en", {}),
    ("EN-postfix", "This platinum ring is unwanted.", "en", {}),
    ("EN-prefix-rejection", "An unwanted gold ring.", "en", {}),
    ("RU-prefix-rejection", "Нежелательное золото. Кольцо.", "ru", {}),
    ("RU-postfix", "Кольцо из золота мне не подходит.", "ru", {}),
    ("mixed-tentative", "Возможно platinum. Кольцо.", "ru", {}),
    ("EN-hedge-comma", "Maybe, platinum. A ring.", "en", {}),
    ("RU-hedge-comma", "Я сомневаюсь, платина. Кольцо.", "ru", {}),
    ("tentative-list", "Perhaps gold, platinum. A ring.", "en", {}),
    (
        "tentative-contrast",
        "Perhaps platinum, but an oval diamond ring.",
        "en",
        {"center_stone.shape": "oval", "center_stone.material": "diamond"},
    ),
    (
        "EN-lines",
        "An oval diamond ring.\nNo side stones.\nGold body.",
        "en",
        {
            "center_stone.shape": "oval",
            "center_stone.material": "diamond",
            "metal.material": "gold",
        },
    ),
    (
        "RU-reordered",
        "Крапаны не нужны.\nКольцо из золота с овальным алмазом.",
        "ru",
        {
            "metal.material": "gold",
            "center_stone.shape": "oval",
            "center_stone.material": "diamond",
        },
    ),
    (
        "independent-positive",
        "No gold. A platinum ring with an oval diamond.",
        "en",
        {
            "metal.material": "platinum",
            "center_stone.shape": "oval",
            "center_stone.material": "diamond",
        },
    ),
)
CHECKED_FIELDS = ("metal.material", "metal.color", "center_stone.shape", "center_stone.material")


def _field(revision, path):
    value = revision.design
    for key in path.split("."):
        value = getattr(value, key)
    return value


@contextmanager
def _scenario(engine, tmp_path, monkeypatch, *, binding=False, locale="en"):
    config, active, report = _release(tmp_path, bundle=p010_bundle() if binding else None)
    client, app, provider = _client(engine, config)
    runtime = app.state.prompt_enrichment_service
    evaluations = []
    evaluate = runtime._evaluate

    def observe(revision, parsed, source):
        result = evaluate(revision, parsed, source)
        evaluations.append((revision, parsed, result))
        return result

    monkeypatch.setattr(runtime, "_evaluate", observe)
    from jewelai_api import correction_enrichment

    correct_evaluate = correction_enrichment.enrich_parsed_candidates_with_active_release

    def observe_correction(revision, **kwargs):
        result = correct_evaluate(revision, **kwargs)
        evaluations.append((revision, kwargs["parse_result"], result))
        return result

    monkeypatch.setattr(
        correction_enrichment, "enrich_parsed_candidates_with_active_release", observe_correction
    )
    with client:
        org, _, response = create_hierarchy(client, locale=locale)
        sid = response.json()["session_id"]
        headers = {"X-Organization-ID": org}
        upgrade = client.post(
            f"/sessions/{sid}/schema-v1-1-upgrade",
            headers=headers,
            json={"expected_revision_id": response.json()["current_revision_id"]},
        )
        assert upgrade.status_code == 200, upgrade.json()
        assert has_p010_binding(runtime._load_release().compiled_runtime) is binding
        yield SimpleNamespace(
            client=client,
            app=app,
            provider=provider,
            runtime=runtime,
            repo=runtime.repository,
            sid=UUID(sid),
            org=UUID(org),
            headers=headers,
            config=config,
            active=active,
            report=report,
            evaluations=evaluations,
            backend=engine.dialect.name,
        )


def _current(ctx):
    return ctx.repo.get_current_revision(ctx.sid, ctx.org)


def _submit(ctx, text, route="initial"):
    before = _current(ctx)
    message = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
    index = len(ctx.evaluations)
    response = ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/{route}",
        headers=ctx.headers,
        json={"expected_revision_id": str(before.revision_id), "message_id": message["message_id"]},
    )
    assert response.status_code == (201 if route == "initial" else 200), response.json()
    after = _current(ctx)
    _, parsed, evaluated = ctx.evaluations[index]
    state = ctx.runtime.get_current_state(ctx.sid, ctx.org)
    prompt = state.final_output.internal_final_prompt
    assert prompt.schema_version == "2.1.0"
    assert ctx.provider.calls == []
    assert ctx.repo.get_message(ctx.sid, UUID(message["message_id"]), ctx.org).content == text
    for candidate in parsed.candidates:
        assert text[candidate.evidence.start : candidate.evidence.end] == candidate.evidence.text
    print(
        "C1_TRACE "
        + json.dumps(
            {
                "backend": ctx.backend,
                "input": text,
                "message_id": message["message_id"],
                "release": state.knowledge_release.model_dump(mode="json"),
                "parser": [c.model_dump(mode="json") for c in parsed.candidates],
                "dispositions": [
                    {
                        "candidate_id": d.candidate.candidate_id,
                        "outcome": d.outcome,
                        "reason": d.reason,
                    }
                    for d in evaluated.dispositions
                ],
                "matrix": [
                    d.model_dump(mode="json") for d in evaluated.enrichment_result.decisions
                ],
                "before": before.design.model_dump(mode="json"),
                "after": after.design.model_dump(mode="json"),
                "description": state.final_output.description.text,
                "ifp": prompt.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
    )
    return before, after, state, message


def exercise_core_case(engine, tmp_path, monkeypatch, case, binding):
    case_id, text, locale, expected = case
    with _scenario(engine, tmp_path, monkeypatch, binding=binding, locale=locale) as ctx:
        _, actual, state, message = _submit(ctx, text)
        facts = {f.target: f for f in state.final_output.internal_final_prompt.design_facts}
        for path in CHECKED_FIELDS:
            value = _field(actual, path)
            if path in expected:
                assert value is not None and value.value == expected[path], (path, value)
                assert value.source.message_id == message["message_id"]
                assert facts[path].value == expected[path]
                assert message["message_id"] in facts[path].source_ids
                label = ctx.runtime.artifacts.dictionary[expected[path]].canonical_terms.for_locale(
                    DictionaryLocale(locale)
                )
                assert label in state.final_output.description.text
            else:
                assert value is None, (path, value)
                assert path not in facts
        assert actual.design.side_stones == ()
        candidates = ctx.evaluations[0][1].candidates
        materials = [c for c in candidates if c.target == "metal.material"]
        if case_id in {"C1-01", "EN-postfix", "RU-postfix"}:
            assert materials and all(c.classification == "prohibition" for c in materials)
        if case_id in {"C1-10", "mixed-tentative"}:
            assert materials and all(c.certainty == "ambiguous" for c in materials)
        original = ctx.repo.list_revisions(ctx.sid, ctx.org)
        cycles = ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)
        pin = ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org)
        final = state.final_output.model_dump(mode="json")
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        restored = app.state.prompt_enrichment_service
        response = restarted.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
        )
        assert response.status_code == 200, response.json()
        assert (
            restored.get_current_state(ctx.sid, ctx.org).final_output.model_dump(mode="json")
            == final
        )
        assert restored.repository.list_revisions(ctx.sid, ctx.org) == original
        assert restored.repository.list_enrichment_cycles(ctx.sid, ctx.org) == cycles
        assert restored.repository.get_knowledge_release_pin(ctx.sid, ctx.org) == pin
        assert provider.calls == []


@pytest.mark.parametrize("binding", (False, True), ids=("without-P010", "with-P010"))
@pytest.mark.parametrize("case", C1_CASES, ids=[c[0] for c in C1_CASES])
def test_core_initial_http(engine, tmp_path, monkeypatch, case, binding):
    exercise_core_case(engine, tmp_path, monkeypatch, case, binding)


def _seed(ctx, *, style=False, material=False):
    """Existing authorized domain/CAS boundary, not a new text-to-target binding."""
    current = _current(ctx)
    message = _message(
        ctx.client,
        str(ctx.sid),
        str(ctx.org),
        "Explicit synthetic approved canonical prerequisites",
    )
    source = MessageSource(message_id=message["message_id"], recorded_at=NOW)
    design = current.design.model_dump(mode="json")
    explicit = {
        "availability": "value",
        "origin": "explicit",
        "source": source.model_dump(mode="json"),
        "confirmed": False,
        "locked": False,
    }
    if style:
        design["style_descriptors"] = {**explicit, "value": ["minimalist"]}
        path = "style_descriptors"
    if material:
        design["metal"]["material"] = {**explicit, "value": "gold"}
        path = "metal.material"
    changed = revise_design(
        current,
        design,
        expected_revision_id=current.revision_id,
        source=source,
        reason="Explicit fixture fact",
        created_at=NOW,
    )
    ctx.repo.append_revision_cas(ctx.sid, ctx.org, current.revision_id, changed)
    confirmed = confirm_field(
        changed,
        path,
        expected_revision_id=changed.revision_id,
        source=source,
        reason="Explicit fixture confirmation",
        created_at=NOW,
    )
    ctx.repo.append_revision_cas(ctx.sid, ctx.org, changed.revision_id, confirmed)
    return confirmed


@pytest.mark.parametrize("locale", ("en", "ru"))
def test_core_style_description_http(engine, tmp_path, monkeypatch, locale):
    with _scenario(engine, tmp_path, monkeypatch, locale=locale) as ctx:
        original = _seed(ctx, style=True)
        _, current, state, _ = _submit(ctx, "A ring." if locale == "en" else "Кольцо.")
        assert current.design.style_descriptors == original.design.style_descriptors
        fact = next(
            f
            for f in state.final_output.internal_final_prompt.design_facts
            if f.target == "style_descriptors"
        )
        assert fact.value == ["minimalist"] and fact.confirmed
        assert (
            "minimalist" if locale == "en" else "минимализм"
        ) in state.final_output.description.text
        output = state.final_output.model_dump(mode="json")
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        assert (
            restarted.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/state", headers=ctx.headers
            ).status_code
            == 200
        )
        assert (
            app.state.prompt_enrichment_service.get_current_state(
                ctx.sid, ctx.org
            ).final_output.model_dump(mode="json")
            == output
        )
        assert provider.calls == []


@pytest.mark.parametrize("binding", (False, True))
def test_core_confirmed_material_http(engine, tmp_path, monkeypatch, binding):
    with _scenario(engine, tmp_path, monkeypatch, binding=binding) as ctx:
        original = _seed(ctx, material=True)
        _submit(ctx, "A gold ring.")
        _, current, state, _ = _submit(ctx, "A platinum ring is not what I want.", "corrections")
        assert current.design.metal.material == original.design.metal.material
        fact = next(
            f
            for f in state.final_output.internal_final_prompt.design_facts
            if f.target == "metal.material"
        )
        assert fact.value == "gold" and fact.confirmed


def test_core_locked_material_cannot_be_replaced(engine, tmp_path, monkeypatch):
    with _scenario(engine, tmp_path, monkeypatch) as ctx:
        confirmed = _seed(ctx, material=True)
        source = confirmed.design.metal.material.source
        locked = lock_field(
            confirmed,
            "metal.material",
            expected_revision_id=confirmed.revision_id,
            source=source,
            reason="Explicit fixture lock",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, confirmed.revision_id, locked)
        _submit(ctx, "A gold ring.")
        _, after, _, _ = _submit(ctx, "Change the metal to platinum.", "corrections")
        assert after.design.metal.material == locked.design.metal.material


@pytest.mark.parametrize(
    "text",
    (
        "Maybe add a halo. A gold ring.",
        "A gold ring. Perhaps no side stones.",
        "A gold ring. Возможно add a halo.",
        "No platinum, but a gold ring.",
    ),
)
def test_core_qualified_instructions_http(engine, tmp_path, monkeypatch, text):
    with _scenario(engine, tmp_path, monkeypatch) as ctx:
        _, current, state, _ = _submit(ctx, text)
        assert current.design.metal.material.value == "gold"
        if "Maybe" in text or "Perhaps" in text or "Возможно" in text:
            assert not any(
                e.status == "active"
                and e.semantic_subject in {"feature.halo", "feature.side_stones"}
                for e in state.clarification_plan.constraint_evidence
            )


def _immutable_history(ctx):
    return {
        "revisions": {
            str(r.revision_id): r.model_dump_json()
            for r in ctx.repo.list_revisions(ctx.sid, ctx.org)
        },
        "cycles": {
            str(c.enrichment_cycle_id): c.result.model_dump_json()
            for c in ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)
        },
        "plans": {
            str(c.enrichment_cycle_id): json.dumps(
                asdict(
                    ctx.repo.get_clarification_plan_for_cycle(
                        ctx.sid, c.enrichment_cycle_id, ctx.org
                    )
                ),
                sort_keys=True,
                default=str,
            )
            for c in ctx.repo.list_enrichment_cycles(ctx.sid, ctx.org)
        },
        "corrections": {
            str(r.correction_record_id): json.dumps(asdict(r), sort_keys=True, default=str)
            for r in ctx.repo.list_user_corrections(ctx.sid, ctx.org)
        },
        "answers": {
            str(r.answer_record_id): json.dumps(asdict(r), sort_keys=True, default=str)
            for r in ctx.repo.list_clarification_answers(ctx.sid, ctx.org)
        },
    }


def exercise_core_lifecycle(engine, tmp_path, monkeypatch, binding):
    with _scenario(engine, tmp_path, monkeypatch, binding=binding) as ctx:
        original = _seed(ctx, material=True)
        _, _, initial, _ = _submit(ctx, "A gold ring. No prongs.")
        initial_history = _immutable_history(ctx)
        initial_pin = ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org)
        _, rejected, _, _ = _submit(ctx, "A platinum ring is not what I want.", "corrections")
        assert rejected.design.metal.material == original.design.metal.material
        _, changed, _, material_message = _submit(
            ctx, "Change the metal to platinum.", "corrections"
        )
        assert changed.design.metal.material.value == "platinum"
        assert not changed.design.metal.material.confirmed
        assert changed.design.metal.material.source.message_id == material_message["message_id"]
        material = changed.design.metal.material
        _, _, preference, _ = _submit(ctx, "I prefer white.", "corrections")
        question = next(
            q for q in preference.clarification_plan.questions if q.target.value == "metal.color"
        )
        answer_message = _message(ctx.client, str(ctx.sid), str(ctx.org), "white")
        answer = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers",
            headers=ctx.headers,
            json={
                "clarification_plan_id": str(preference.clarification_plan_id),
                "clarification_id": question.clarification_id,
                "decision": "ACCEPT",
                "answer_id": str(uuid4()),
                "expected_revision_id": str(preference.authoritative_revision_id),
                "message_id": answer_message["message_id"],
            },
        )
        assert answer.status_code == 200, answer.json()
        _, final_revision, final_state, stone_message = _submit(
            ctx, "An oval diamond center stone in a prong setting. No side stones.", "corrections"
        )
        assert final_revision.design.metal.material == material
        assert final_revision.design.metal.color.value == "white"
        assert final_revision.design.center_stone.shape.value == "oval"
        assert final_revision.design.center_stone.material.value == "diamond"
        assert (
            final_revision.design.center_stone.material.source.message_id
            == stone_message["message_id"]
        )
        assert final_revision.design.side_stones == ()
        assert final_state.enrichment_cycle_number == 6
        final = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert final.status_code == 200, final.json()
        prompt = final.json()["internal_final_prompt"]
        assert prompt["schema_version"] == "2.1.0"
        facts = {f["target"]: f["value"] for f in prompt["design_facts"]}
        assert facts["metal.material"] == "platinum"
        assert facts["center_stone.material"] == "diamond"
        assert "platinum" in prompt["description"]["text"]
        assert "diamond" in prompt["description"]["text"]
        assert any(
            c["target"] == "feature.side_stones" and c["kind"] == "prohibition"
            for c in prompt["constraints"]
        )
        history = _immutable_history(ctx)
        for collection, records in initial_history.items():
            assert all(history[collection].get(key) == value for key, value in records.items())
        assert ctx.repo.get_knowledge_release_pin(ctx.sid, ctx.org) == initial_pin
        stale_message = _message(ctx.client, str(ctx.sid), str(ctx.org), "A sapphire ring.")
        stale = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers=ctx.headers,
            json={
                "expected_revision_id": str(initial.authoritative_revision_id),
                "message_id": stale_message["message_id"],
            },
        )
        assert stale.status_code == 409, stale.json()
        other_org, _, _ = create_hierarchy(ctx.client)
        scoped = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state",
            headers={"X-Organization-ID": other_org},
        )
        assert scoped.status_code == 404, scoped.json()
        denied = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state",
            headers={**ctx.headers, "Authorization": "Bearer test-unrelated"},
        )
        # Existing membership lookup intentionally returns a scoped 404.
        assert denied.status_code == 404, denied.json()
        forbidden_write = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/corrections",
            headers={"X-Organization-ID": other_org},
            json={
                "expected_revision_id": str(final_revision.revision_id),
                "message_id": stone_message["message_id"],
            },
        )
        assert forbidden_write.status_code == 404, forbidden_write.json()
        assert _immutable_history(ctx) == history
        assert ctx.provider.calls == []
    restarted, app, provider = _client(engine, ctx.config)
    with restarted:
        restored = app.state.prompt_enrichment_service
        restored_response = restarted.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/final-output", headers=ctx.headers
        )
        assert restored_response.status_code == 200, restored_response.json()
        assert restored_response.json() == final.json()
        assert restored.repository.get_current_revision(ctx.sid, ctx.org) == final_revision
        assert restored.repository.get_knowledge_release_pin(ctx.sid, ctx.org) == initial_pin
        restored_ctx = SimpleNamespace(repo=restored.repository, sid=ctx.sid, org=ctx.org)
        assert _immutable_history(restored_ctx) == history
        assert provider.calls == []
    print(
        "C1_LIFECYCLE_TRACE "
        + json.dumps(
            {
                "backend": ctx.backend,
                "p010": binding,
                "cycles": 6,
                "confirmed_rejection_preserved": True,
                "authorized_correction": "platinum",
                "clarification": answer.status_code,
                "final_ifp_version": prompt["schema_version"],
                "stale_cas": stale.status_code,
                "tenant_scope": scoped.status_code,
                "membership": denied.status_code,
                "restart_identical": True,
                "historical_bytes_unchanged": True,
                "pin_unchanged": True,
            }
        )
    )


@pytest.mark.parametrize("binding", (False, True))
def test_core_six_cycle_http(engine, tmp_path, monkeypatch, binding):
    exercise_core_lifecycle(engine, tmp_path, monkeypatch, binding)
