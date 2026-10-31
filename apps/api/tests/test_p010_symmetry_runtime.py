"""Authentic approved content in an explicitly TEST-ONLY qualified release."""

import json
from uuid import UUID, uuid4

import pytest
from conftest import ROOT, create_hierarchy
from test_prompt_enrichment_composition import _client, _release
from test_prompt_enrichment_http import _message

REVIEW_NEGATIVES = (
    "Асимметричное кольцо не нужно.",
    "Не хочу, чтобы было асимметричное кольцо.",
    "An asymmetric ring is not what I want.",
    "Я сомневаюсь, нужно ли асимметричное кольцо.",
    "An asymmetric design for the website.",
    "An asymmetric composition for the photograph.",
)
F00_NEGATIVE_LISTS = (
    "An asymmetric ring, no halo, engraving or asymmetry.",
    "An asymmetric ring, no halo, engraving and asymmetry.",
    "An asymmetric ring, no halo,\nengraving,\nasymmetry.",
    "An asymmetric ring, no halo,engraving,asymmetry.",
    "An asymmetric ring, without engraving, halo or asymmetry.",
    "Асимметричное кольцо, без гало, гравировки или асимметрии.",
    "An asymmetric ring. No halo, engraving or asymmetry.",
    "An asymmetric ring, no halo, engraving or asymmetry — do not make it symmetrical.",
    "An asymmetric ring, no halo, yellow gold or oval diamond.",
)


@pytest.mark.parametrize("text", F00_NEGATIVE_LISTS)
def test_f00_shared_negative_scope_http(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text)


@pytest.mark.parametrize("text", ["An asymmetric ring road.", "An asymmetric jewelry diagram."])
def test_f00_unknown_product_compound_http(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text)


SCOPE_REVIEW_CASES = (
    ("Асимметричное кольцо\nне нужно.", False, False, False),
    ("An asymmetric ring\nis not what I want.", False, False, False),
    ("An asymmetric ring\nphotograph.", False, False, False),
    ("An asymmetric jewelry\nwebsite design.", False, False, False),
    ("An asymmetric ring. Maybe,\ndo not make it symmetrical.", True, False, False),
    ("An asymmetric ring. I don't mean,\ndo not make it symmetrical.", True, False, False),
    ("An asymmetric ring, no halo.", True, False, True),
    ("An asymmetric ring without a halo.", True, False, True),
    ("Асимметричное кольцо без гало.", True, False, True),
)


SCOPE_CONTROLS = (
    ("Асимметричное кольцо — не выравнивай его.", True, True, False),
    ("An asymmetric ring, no halo. Do not make it symmetrical.", True, True, True),
    ("An asymmetric ring.\nNo halo.", True, False, True),
    ("No halo. An asymmetric ring.", True, False, True),
    ("An asymmetrical jewelry design.", True, False, False),
    ("Не хочу,\nчтобы было асимметричное кольцо.", False, False, False),
    ("An asymmetric ring\nis unnecessary.", False, False, False),
    ("An asymmetric ring.\nMaybe, do not make it symmetrical.", True, False, False),
    ("Асимметричное кольцо\nбез гало — не выравнивай его.", True, True, True),
    ("An asymmetric ring, no halo — do not\nmake it symmetrical.", True, True, True),
    ("No asymmetric ring without a halo.", False, False, True),
    ("No halo or an asymmetric ring.", False, False, True),
    ("An asymmetric ring, do not add a halo — do not make it symmetrical.", True, True, True),
    ("An asymmetric ring, without engraving.", True, False, False),
    ("No halo;\nAn asymmetric ring.", True, False, True),
    # With no explicit statement boundary, a shared negative list is ambiguous.
    ("No halo\nAn asymmetric ring.", False, False, True),
    ("An asymmetric ring, no halo or asymmetry.", False, False, True),
    ("An asymmetric ring, no halo or side stones.", False, False, True),
)


def exercise_p010_rejected_http(
    engine,
    tmp_path,
    monkeypatch,
    text,
    *,
    symmetry=False,
    keep=False,
    halo=False,
    finish=False,
    metal=False,
    unresolved_symmetry=False,
    finish_correction_text=None,
):
    config, active, report = _release(tmp_path, bundle=p010_bundle())
    client, app, provider = _client(engine, config)
    observed = []
    from jewelai_parser import parse_full_message

    def observe(*args, **kwargs):
        result = parse_full_message(*args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr("jewelai_api.prompt_enrichment_runtime.parse_full_message", observe)
    service = app.state.prompt_enrichment_service
    evaluate = service._evaluate
    evaluations = []

    def observe_evaluation(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        evaluations.append(result)
        return result

    monkeypatch.setattr(service, "_evaluate", observe_evaluation)
    with client:
        org, project, _ = create_hierarchy(client)
        response = client.post(
            f"/projects/{project}/sessions",
            headers={"X-Organization-ID": org},
            json={"role_id": "retail_client", "locale": "ru-RU" if "кольцо" in text else "en-US"},
        )
        assert response.status_code == 201
        sid = response.json()["session_id"]
        headers = {"X-Organization-ID": org}
        upgrade = client.post(
            f"/sessions/{sid}/schema-v1-1-upgrade",
            headers=headers,
            json={"expected_revision_id": response.json()["current_revision_id"]},
        )
        assert upgrade.status_code == 200 and upgrade.json()["design"]["composition"] is None
        message = _message(client, sid, org, text)
        result = client.post(
            f"/v1/sessions/{sid}/prompt-enrichment/initial",
            headers=headers,
            json={
                "expected_revision_id": upgrade.json()["revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert result.status_code == 201, result.json()
        repo = app.state.prompt_enrichment_service.repository
        revision = repo.get_current_revision(UUID(sid), UUID(org))
        if symmetry:
            value = revision.design.composition.value.symmetry_mode
            assert value.value == "asymmetrical" and not value.confirmed and not value.locked
            assert value.source.message_id == message["message_id"]
        else:
            assert revision.design.composition is None
        # Existing parser may retain the explicitly mentioned product category;
        # no composition or unrelated design facts may be invented.
        allowed = (
            {"jewelry_type"}
            | ({"composition"} if symmetry else set())
            | ({"metal"} if metal else set())
        )
        assert {
            key: value
            for key, value in revision.design.model_dump(mode="json").items()
            if key not in allowed
        } == {key: value for key, value in upgrade.json()["design"].items() if key not in allowed}
        if metal:
            assert revision.design.metal.color.value == "yellow"
            assert revision.design.metal.material.value == "gold"
            assert revision.design.metal.color.source.message_id == message["message_id"]
            assert revision.design.metal.material.source.message_id == message["message_id"]
        assert observed[0].original_text == text
        assert observed[0].knowledge_runtime_sha256 == active.runtime_sha256
        assert (
            any(
                c.semantic_subject == "composition.symmetry_mode"
                and c.classification == "requirement"
                and c.certainty == "explicit"
                for c in observed[0].candidates
            )
            is symmetry
        )
        cycles = repo.list_enrichment_cycles(UUID(sid), UUID(org))
        assert len(cycles) == 1
        assert (
            any(
                d.outcome == "APPLIED" and d.target in {"composition", "composition.symmetry_mode"}
                for d in evaluations[0].enrichment_result.decisions
            )
            is symmetry
        )
        if not symmetry:
            assert not any(
                d.outcome == "APPLIED" and d.target in {"composition", "composition.symmetry_mode"}
                for d in cycles[0].result.decisions
            )
        else:
            cell = next(
                c for c in cycles[0].result.final_matrix if c.target == "composition.symmetry_mode"
            )
            assert cell.value == "asymmetrical"
            assert set(cell.applicable_policy_ids) == {"STYLE-10-02", "STYLE-10-06", "STYLE-10-07"}
        binding = repo.get_knowledge_release_pin(UUID(sid), UUID(org))
        assert binding.binding.runtime_sha256 == active.runtime_sha256
        assert binding.binding.validation_report_sha256 == report.sha256
        assert repo.get_message(UUID(sid), UUID(message["message_id"]), UUID(org)).content == text
        state = client.get(f"/v1/sessions/{sid}/prompt-enrichment/state", headers=headers)
        assert state.status_code == 200
        plan = app.state.prompt_enrichment_service.restore_clarification_plan(
            UUID(sid), UUID(org), UUID(state.json()["clarification_plan_id"]), require_current=True
        )
        if symmetry:
            requirement = next(
                e
                for e in plan.constraint_evidence
                if e.semantic_subject == "composition.symmetry_mode"
                and e.kind == "requirement"
                and e.canonical_target == "composition.symmetry_mode"
            )
            assert requirement.canonical_target == "composition.symmetry_mode"
            assert requirement.status == ("superseded" if keep else "active")
            assert requirement.source.message_id == message["message_id"]
            assert (
                text[requirement.source_span_start : requirement.source_span_end]
                == requirement.original_wording
            )
            assert requirement.source_candidate_id in {
                c.candidate_id for c in observed[0].candidates
            }
            if keep:
                assert any(
                    e.evidence_id == requirement.superseded_by_evidence_id
                    and e.kind == "preservation"
                    and e.status == "active"
                    for e in plan.constraint_evidence
                )
        assert (
            any(
                e.semantic_subject == "composition.symmetry_mode"
                and e.kind == "preservation"
                and e.status == "active"
                for e in plan.constraint_evidence
            )
            is keep
        )
        if halo:
            assert any(
                c.semantic_subject == "feature.halo" and c.classification == "prohibition"
                for c in observed[0].candidates
            )
            assert any(
                e.semantic_subject == "feature.halo"
                and e.kind == "prohibition"
                and e.status == "active"
                for e in plan.constraint_evidence
            )
        if "without engraving" in text or "no engraving" in text:
            assert any(
                e.semantic_subject == "feature.engraving"
                and e.kind == "prohibition"
                and e.status == "active"
                for e in plan.constraint_evidence
            )
        for candidate in observed[0].candidates:
            span = candidate.evidence
            assert text[span.start : span.end] == span.text
        assert provider.calls == []
        revision_url = f"/sessions/{sid}/revisions/{revision.revision_id}"
        persisted = client.get(revision_url, headers=headers)
        assert persisted.status_code == 200
        assert persisted.json()["design"] == revision.design.model_dump(mode="json")
        trace = {
            "input": text,
            "parser": [
                {
                    "classification": c.classification,
                    "certainty": c.certainty,
                    "wording": c.evidence.text,
                    "detail": c.detail,
                }
                for c in observed[0].candidates
                if c.semantic_subject == "composition.symmetry_mode"
            ],
            "knowledge_runtime_sha256": binding.binding.runtime_sha256,
            "knowledge_package_id": binding.binding.package_id,
            "validation_report_sha256": binding.binding.validation_report_sha256,
            "dispositions": [
                {"outcome": d.outcome, "reason": d.reason, "wording": d.candidate.evidence.text}
                for d in evaluations[0].dispositions
                if d.candidate.semantic_subject == "composition.symmetry_mode"
            ],
            "matrix_decisions": [
                {"target": d.target, "outcome": d.outcome}
                for d in evaluations[0].enrichment_result.decisions
            ],
            "canonical_symmetry": "asymmetrical" if symmetry else None,
            "initial_dictionary_fields": {
                "metal": revision.design.metal.model_dump(mode="json"),
                "center_stone": revision.design.center_stone.model_dump(mode="json"),
            },
            "dictionary_dispositions": [
                {
                    "target": d.candidate.target,
                    "wording": d.candidate.evidence.text,
                    "outcome": d.outcome,
                    "reason": d.reason,
                }
                for d in evaluations[0].dispositions
                if d.candidate.target is not None
            ],
            "constraint_evidence": [
                {
                    "subject": e.semantic_subject,
                    "kind": e.kind,
                    "status": e.status,
                    "canonical_target": e.canonical_target,
                    "source_candidate_id": e.source_candidate_id,
                    "span": [e.source_span_start, e.source_span_end],
                    "wording": e.original_wording,
                }
                for e in plan.constraint_evidence
            ],
            "active_constraints": [
                e.semantic_subject for e in plan.constraint_evidence if e.status == "active"
            ],
        }

    restarted, restored_app, restored_provider = _client(engine, config)
    with restarted:
        state = restarted.get(f"/v1/sessions/{sid}/prompt-enrichment/state", headers=headers)
        assert state.status_code == 200, state.json()
        restored_repo = restored_app.state.prompt_enrichment_service.repository
        assert restored_repo.get_current_revision(UUID(sid), UUID(org)) == revision
        assert restored_repo.list_enrichment_cycles(UUID(sid), UUID(org)) == cycles
        assert restored_repo.get_knowledge_release_pin(UUID(sid), UUID(org)) == binding
        restored_plan = restored_app.state.prompt_enrichment_service.restore_clarification_plan(
            UUID(sid), UUID(org), UUID(state.json()["clarification_plan_id"]), require_current=True
        )
        assert restored_plan == plan
        restored_revision = restarted.get(revision_url, headers=headers)
        assert restored_revision.status_code == 200 and restored_revision.json() == persisted.json()
        assert restored_provider.calls == []
        if finish:
            prompt = _finish_f00_lifecycle(
                restarted,
                restored_app,
                sid,
                org,
                headers,
                state.json(),
                symmetry,
                keep,
                binding,
                tuple(
                    (e.semantic_subject, e.kind)
                    for e in plan.constraint_evidence
                    if e.status == "active"
                ),
                message["message_id"],
                unresolved_symmetry,
                correction_text=finish_correction_text,
            )
            trace["ifp_symmetry"] = [
                f["value"]
                for f in prompt["design_facts"]
                if f["target"] == "composition.symmetry_mode"
            ]
            trace["ifp_keep"] = any(
                c["target"] == "composition.symmetry_mode" and c["kind"] == "preservation"
                for c in prompt["constraints"]
            )
            trace["description"] = prompt["description"]["text"]
            trace["ifp_unresolved_targets"] = [d["target"] for d in prompt["unresolved_details"]]
            if "that part" in text:
                # Fixing a fulfilled canonical requirement must not suppress an
                # independent, genuinely unresolved preservation instruction.
                assert any(
                    e["status"] == "unresolved" and "that part" in e["original_wording"]
                    for e in prompt["constraint_evidence"]
                )
                assert "constraint.unresolved" in trace["ifp_unresolved_targets"]
    if finish:
        fresh, fresh_app, fresh_provider = _client(engine, config)
        with fresh:
            final = fresh.get(f"/v1/sessions/{sid}/prompt-enrichment/final-output", headers=headers)
            assert final.status_code == 200 and final.json()["internal_final_prompt"] == prompt
            final_repo = fresh_app.state.prompt_enrichment_service.repository
            assert (
                final_repo.get_message(UUID(sid), UUID(message["message_id"]), UUID(org)).content
                == text
            )
            assert final_repo.get_knowledge_release_pin(UUID(sid), UUID(org)) == binding
            assert fresh_provider.calls == []
        print("F00_TRACE " + json.dumps(trace, ensure_ascii=False))
    return trace


def _description_without_unapplied_citations(prompt):
    """Keep negative fact-claim assertions strict while checking sourced quotations separately."""
    text = prompt["description"]["text"]
    prefix = (
        "Source phrase with unresolved details"
        if prompt["locale"] == "en"
        else "Исходная фраза с неприменёнными деталями"
    )
    for evidence in prompt["constraint_evidence"]:
        if (
            evidence["kind"] == "requirement"
            and evidence["status"] == "unresolved"
            and evidence["semantic_subject"] is None
            and evidence["canonical_target"] is None
        ):
            assert evidence["acceptance"] == "unresolved"
            text = text.replace(f"{prefix}: «{evidence['original_wording']}»", "")
    return text


def _finish_f00_lifecycle(
    client,
    app,
    sid,
    org,
    headers,
    state,
    symmetry,
    keep,
    binding,
    active_constraints,
    initial_message_id,
    unresolved_symmetry,
    *,
    correction_text=None,
    preceding_cycles=1,
):
    correction_message = _message(
        client,
        sid,
        org,
        correction_text
        or "A white or yellow gold ring with an oval sapphire center stone. No halo.",
    )
    correction = client.post(
        f"/v1/sessions/{sid}/prompt-enrichment/corrections",
        headers=headers,
        json={
            "expected_revision_id": state["authoritative_revision_id"],
            "message_id": correction_message["message_id"],
        },
    )
    assert correction.status_code == 200, correction.json()
    current = correction.json()["state"]
    question = next(
        q
        for q in current["clarification_questions"]
        if any(o["value"] == "yellow" for o in q["options"])
    )
    answer_message = _message(client, sid, org, "yellow")
    answer = client.post(
        f"/v1/sessions/{sid}/prompt-enrichment/clarification-answers",
        headers=headers,
        json={
            "clarification_plan_id": current["clarification_plan_id"],
            "clarification_id": question["clarification_id"],
            "decision": "SELECT_OPTION",
            "selected_option": "yellow",
            "answer_id": str(uuid4()),
            "expected_revision_id": current["authoritative_revision_id"],
            "message_id": answer_message["message_id"],
        },
    )
    assert answer.status_code == 200, answer.json()
    final = client.get(f"/v1/sessions/{sid}/prompt-enrichment/final-output", headers=headers)
    assert final.status_code == 200, final.json()
    prompt = final.json()["internal_final_prompt"]
    assert prompt["schema_version"] == "2.1.0"
    facts = [f for f in prompt["design_facts"] if f["target"] == "composition.symmetry_mode"]
    assert bool(facts) is symmetry
    assert ('composition.symmetry_mode = "asymmetrical"' in prompt["prompt_text"]) is symmetry
    if not symmetry:
        current_claims = _description_without_unapplied_citations(prompt).casefold()
        assert "asymmetrical" not in current_claims
        assert "асимметрич" not in current_claims
        assert not any(
            c["target"] == "composition.symmetry_mode" and c["kind"] != "prohibition"
            for c in prompt["constraints"]
        )
    if symmetry:
        assert (
            facts[0]["value"] == "asymmetrical"
            and not facts[0]["confirmed"]
            and not facts[0]["locked"]
        )
        assert (
            any(d["target"] == "composition.symmetry_mode" for d in prompt["unresolved_details"])
            is unresolved_symmetry
        ), prompt["description"]
        assert (
            any(
                e["semantic_subject"] == "composition.symmetry_mode" and e["status"] == "unresolved"
                for e in prompt["constraint_evidence"]
            )
            is unresolved_symmetry
        )
        description = prompt["description"]["text"]
        assert ("асимметричная" if prompt["locale"] == "ru" else "asymmetrical") in description
        if unresolved_symmetry:
            assert (
                "Неуточнённый запрос о composition symmetry mode"
                if prompt["locale"] == "ru"
                else "Unresolved request about composition symmetry mode"
            ) in description
        else:
            assert "composition symmetry mode: неоднозначно" not in description
            assert "composition symmetry mode: ambiguous" not in description
    for fact in prompt["design_facts"]:
        if fact["target"].startswith(("metal.", "center_stone.")):
            assert initial_message_id not in fact["source_ids"]
    assert (
        any(
            c["target"] == "composition.symmetry_mode" and c["kind"] == "preservation"
            for c in prompt["constraints"]
        )
        is keep
    )
    for subject, kind in active_constraints:
        assert any(c["target"] == subject and c["kind"] == kind for c in prompt["constraints"])
    repo = app.state.prompt_enrichment_service.repository
    cycles = repo.list_enrichment_cycles(UUID(sid), UUID(org))
    assert len(cycles) == preceding_cycles + 2
    for cycle in cycles:
        cells = [c for c in cycle.result.final_matrix if c.target == "composition.symmetry_mode"]
        assert bool(cells) is symmetry
        if symmetry:
            assert (
                cells[0].value == "asymmetrical" and not cells[0].confirmed and not cells[0].locked
            )
            assert set(cells[0].applicable_policy_ids) == {
                "STYLE-10-02",
                "STYLE-10-06",
                "STYLE-10-07",
            }
    assert repo.get_knowledge_release_pin(UUID(sid), UUID(org)) == binding
    stale = client.post(
        f"/v1/sessions/{sid}/prompt-enrichment/corrections",
        headers=headers,
        json={
            "expected_revision_id": state["authoritative_revision_id"],
            "message_id": correction_message["message_id"],
        },
    )
    assert stale.status_code == 409 and repo.list_enrichment_cycles(UUID(sid), UUID(org)) == cycles
    return prompt


F00_LIFECYCLES = (
    ("No white or yellow gold, oval diamond. An asymmetric ring.", True, False, False),
    ("An asymmetric ring, no white or yellow gold, oval diamond.", False, False, False),
    ("An asymmetric ring, no oval or round diamond, yellow gold.", False, False, False),
    ("An asymmetric ring is not what I want in gold.", False, False, False),
    ("An asymmetric ring is not.", False, False, False),
    ("An asymmetric ring is unwanted in yellow gold.", False, False, False),
    ("An asymmetric ring, not diamond, yellow gold.", False, False, False),
    ("An asymmetric ring, no mysterious object, yellow gold.", False, False, False),
    ("An asymmetric ring. No asymmetric photograph.", True, False, False),
    ("An asymmetric ring. A symmetrical photograph.", True, False, False),
    ("An asymmetric ring. Do not change that part.", True, False, False),
    ("An asymmetric ring, no diamond.", True, False, False),
    ("An asymmetric ring, no yellow gold.", True, False, False),
    ("An asymmetric ring. No asymmetry.", False, False, False),
    # Independent statements remain independent; formatting is not an operator.
    ("An asymmetric ring. No halo, engraving or side stones.", True, False, True),
    ("No halo, engraving or side stones. An asymmetric ring.", True, False, True),
    ("An asymmetric ring.\nNo halo, engraving or side stones.", True, False, True),
    ("No diamond, yellow gold. An asymmetric ring.", True, False, False),
    ("Асимметричное кольцо. Без гало, гравировки или боковых камней.", True, False, True),
    # Dictionary objects must govern their unresolved list, like special features.
    ("An asymmetric ring, no diamond, yellow gold.", False, False, False),
    ("An asymmetric ring, no yellow gold, oval diamond.", False, False, False),
    ("An asymmetric ring, without sapphire, white gold.", False, False, False),
    ("Асимметричное кольцо, без сапфира, белое золото.", False, False, False),
    ("An asymmetric ring. No halo, engraving or asymmetry.", False, False, True),
    ("Асимметричное кольцо — не выравнивай его.", True, True, False),
    ("An asymmetric ring, no halo, without engraving.", True, False, True),
    ("An asymmetric ring, no halo, engraving or asymmetry.", False, False, True),
    ("An asymmetric ring is not what I want.", False, False, False),
    ("An asymmetric ring\nphotograph.", False, False, False),
    ("Maybe an asymmetric ring.", False, False, False),
    ("An asymmetric ring. Maybe,\ndo not make it symmetrical.", True, False, False),
    ("An asymmetric ring, no halo, yellow gold or oval diamond.", False, False, True),
)


F00_INDEPENDENT_METAL = (
    "No diamond, oval stone. An asymmetric ring in yellow gold.",
    "An asymmetric ring in yellow gold. No diamond, oval stone.",
)


@pytest.mark.parametrize("text", F00_INDEPENDENT_METAL)
def test_f00_independent_dictionary_facts_persist(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text, symmetry=True, metal=True)


def test_f00_unresolved_request_does_not_make_accepted_fact_ambiguous(
    engine, tmp_path, monkeypatch
):
    exercise_p010_rejected_http(
        engine,
        tmp_path,
        monkeypatch,
        "An asymmetric ring. Maybe an asymmetric ring.",
        symmetry=True,
        unresolved_symmetry=True,
        finish=True,
    )


@pytest.mark.parametrize("text,symmetry,keep,halo", F00_LIFECYCLES)
def test_f00_functional_lifecycle_to_ifp(engine, tmp_path, monkeypatch, text, symmetry, keep, halo):
    exercise_p010_rejected_http(
        engine, tmp_path, monkeypatch, text, symmetry=symmetry, keep=keep, halo=halo, finish=True
    )


KEEP_COMPATIBLE_FULL_CORRECTIONS = (
    "An asymmetric ring in white or yellow gold with an oval diamond. No halo.",
    "An asymmetrical jewelry design. White or yellow gold, oval diamond. No halo.",
    "Кольцо должно быть асимметричное. Белое или желтое золото, овальный алмаз. Без гало.",
)


@pytest.mark.parametrize(
    "correction", KEEP_COMPATIBLE_FULL_CORRECTIONS, ids=("en-facts", "en-independent", "ru-facts")
)
def test_keep_survives_compatible_three_cycle_correction(engine, tmp_path, monkeypatch, correction):
    exercise_p010_rejected_http(
        engine,
        tmp_path,
        monkeypatch,
        "Асимметричное кольцо — не выравнивай его.",
        symmetry=True,
        keep=True,
        finish=True,
        finish_correction_text=correction,
    )


KEEP_FOLLOWUPS = (
    ("An asymmetric ring.",),
    ("Кольцо должно быть асимметричное.",),
    ("An asymmetric ring in gold with an oval diamond.",),
    ("No halo.", "Add a halo."),
    ("Maybe an asymmetric ring.",),
    ("An asymmetric ring is not what I want.",),
    ("Make the ring symmetrical.",),
    ("Remove the KEEP instruction.",),
    (
        "An asymmetric ring.",
        "An asymmetrical ring — do not make it symmetrical.",
        "Кольцо должно быть асимметричное.",
        "No halo.",
    ),
)


@pytest.mark.parametrize(
    "followups",
    KEEP_FOLLOWUPS,
    ids=(
        "minimal-en",
        "compatible-ru",
        "independent-facts",
        "halo-replacement",
        "uncertain",
        "rejected",
        "unsupported-conflict",
        "unsupported-cancel",
        "replacement-sequence",
    ),
)
def test_keep_correction_sequence_http(engine, tmp_path, monkeypatch, followups):
    exercise_keep_correction_sequence(engine, tmp_path, monkeypatch, followups)


def test_keep_is_not_a_lock_and_cannot_authorize_stale_handoff(engine, tmp_path, monkeypatch):
    exercise_keep_correction_sequence(engine, tmp_path, monkeypatch, (), external_edit=True)


def exercise_keep_correction_sequence(
    engine, tmp_path, monkeypatch, followups, *, external_edit=False
):
    """Real persisted Messages/corrections; inspect each authoritative cycle, then restart."""
    from jewelai_api.durable_enrichment import list_user_correction_results

    config, active, report = _release(tmp_path, bundle=p010_bundle())
    client, app, provider = _client(engine, config)
    snapshots = []
    with client:
        org, project, _ = create_hierarchy(client)
        headers = {"X-Organization-ID": org}
        response = client.post(
            f"/projects/{project}/sessions",
            headers=headers,
            json={"role_id": "retail_client", "locale": "ru-RU"},
        )
        assert response.status_code == 201
        sid = response.json()["session_id"]
        upgraded = client.post(
            f"/sessions/{sid}/schema-v1-1-upgrade",
            headers=headers,
            json={"expected_revision_id": response.json()["current_revision_id"]},
        )
        assert upgraded.status_code == 200
        initial = _message(client, sid, org, "Асимметричное кольцо — не выравнивай его.")
        response = client.post(
            f"/v1/sessions/{sid}/prompt-enrichment/initial",
            headers=headers,
            json={
                "expected_revision_id": upgraded.json()["revision_id"],
                "message_id": initial["message_id"],
            },
        )
        assert response.status_code == 201, response.json()
        repo = app.state.prompt_enrichment_service.repository
        binding = repo.get_knowledge_release_pin(UUID(sid), UUID(org))
        assert binding.binding.runtime_sha256 == active.runtime_sha256
        assert binding.binding.validation_report_sha256 == report.sha256
        current_keep = None
        history = []

        def snapshot(label, expected_message_id, *, replaces=False):
            nonlocal current_keep
            state = client.get(f"/v1/sessions/{sid}/prompt-enrichment/state", headers=headers)
            assert state.status_code == 200, state.json()
            state = state.json()
            runtime = app.state.prompt_enrichment_service
            plan = runtime.restore_clarification_plan(
                UUID(sid), UUID(org), UUID(state["clarification_plan_id"]), require_current=True
            )
            evidence = [
                e
                for e in plan.constraint_evidence
                if e.semantic_subject == "composition.symmetry_mode"
            ]
            active_evidence = [e for e in evidence if e.status == "active"]
            assert len(active_evidence) == 1 and active_evidence[0].kind == "preservation", evidence
            keeper = active_evidence[0]
            assert keeper.source.message_id == expected_message_id
            original = repo.get_message(UUID(sid), UUID(expected_message_id), UUID(org)).content
            assert (
                original[keeper.source_span_start : keeper.source_span_end]
                == keeper.original_wording
            )
            if current_keep is not None:
                if replaces:
                    old = next(e for e in evidence if e.evidence_id == current_keep.evidence_id)
                    assert (
                        old.status == "superseded"
                        and old.superseded_by_evidence_id == keeper.evidence_id
                    )
                else:
                    assert keeper == current_keep
            current_keep = keeper
            revision = repo.get_current_revision(UUID(sid), UUID(org))
            value = revision.design.composition.value.symmetry_mode
            assert value.value == "asymmetrical" and not value.locked and not value.confirmed
            assert value.source.message_id == initial["message_id"]
            assembly = runtime.get_current_state(UUID(sid), UUID(org)).final_output
            prompt = assembly.internal_final_prompt
            keeps = [
                c
                for c in prompt.constraints
                if c.kind == "preservation" and c.target == keeper.semantic_subject
            ]
            assert len(keeps) == 1 and keeper.evidence_id in keeps[0].source_ids
            assert keeper.normalized_instruction in prompt.prompt_text
            assert state["description"]["text"].count(keeper.normalized_instruction) == 1
            requirements = [
                c
                for c in prompt.constraints
                if c.kind == "requirement" and c.target == keeper.semantic_subject
            ]
            assert len(requirements) == 1 and requirements[0].value == "asymmetrical"
            for record in history:
                assert (
                    repo.get_clarification_plan_for_cycle(
                        UUID(sid), record.enrichment_cycle_id, UUID(org)
                    )
                    == record
                )
            record = repo.get_clarification_plan_for_cycle(
                UUID(sid), UUID(state["enrichment_cycle_id"]), UUID(org)
            )
            history.append(record)
            snapshots.append(
                {
                    "stage": label,
                    "cycle": state["enrichment_cycle_number"],
                    "keeper": keeper.model_dump(mode="json"),
                    "revision_id": str(revision.revision_id),
                    "ifp_keep": True,
                }
            )
            return state

        state = snapshot("initial", initial["message_id"])
        if external_edit:
            # Existing structured EDIT authority is independent of KEEP evidence.
            # It may change an unlocked fact, but cannot reuse an older enrichment
            # cycle/constraint as a valid current handoff. No revocation is invented.
            from conftest import NOW
            from jewelai_domain.revisions import revise_design

            change = _message(client, sid, org, "Explicit test change to symmetrical composition.")
            source = {
                "kind": "message",
                "message_id": change["message_id"],
                "recorded_at": NOW.isoformat(),
            }
            revision = repo.get_current_revision(UUID(sid), UUID(org))
            design = revision.design.model_dump(mode="json")
            design["composition"]["value"]["symmetry_mode"]["value"] = "symmetrical"
            design["composition"]["value"]["symmetry_mode"]["source"] = source
            # Reuse the existing internal Schema1.1 EDIT/CAS boundary; the
            # legacy public revisions route intentionally remains Schema1.0.
            edited = revise_design(
                revision,
                design,
                expected_revision_id=revision.revision_id,
                source=source,
                reason="Explicit test authorized edit",
                created_at=NOW,
            )
            repo.append_revision_cas(UUID(sid), UUID(org), revision.revision_id, edited)
            assert (
                repo.get_current_revision(
                    UUID(sid), UUID(org)
                ).design.composition.value.symmetry_mode.value
                == "symmetrical"
            )
            blocked = client.get(
                f"/v1/sessions/{sid}/prompt-enrichment/final-output", headers=headers
            )
            assert blocked.status_code == 409, blocked.json()
            assert (
                repo.get_clarification_plan_for_cycle(
                    UUID(sid), history[0].enrichment_cycle_id, UUID(org)
                )
                == history[0]
            )
            assert provider.calls == []
            print(
                "F00_KEEP_AUTHORITY_TRACE canonical_edit=APPLIED stale_handoff=409 "
                "historical_evidence_unchanged=true"
            )
            return
        keeper_message_id = initial["message_id"]
        for text in followups:
            message = _message(client, sid, org, text)
            response = client.post(
                f"/v1/sessions/{sid}/prompt-enrichment/corrections",
                headers=headers,
                json={
                    "expected_revision_id": state["authoritative_revision_id"],
                    "message_id": message["message_id"],
                },
            )
            assert response.status_code == 200, response.json()
            correction = next(
                item
                for item in list_user_correction_results(
                    repo, session_id=UUID(sid), organization_id=UUID(org)
                )
                if item.source.message_id == message["message_id"]
            )
            new_keep = any(
                c.classification == "preservation"
                and c.certainty == "explicit"
                and c.semantic_subject == "composition.symmetry_mode"
                for c in correction.parsed_correction.candidates
            )
            if new_keep:
                keeper_message_id = message["message_id"]
            state = snapshot(text, keeper_message_id, replaces=new_keep)
            accepted_reaffirmations = [
                d
                for d in correction.correction_evaluation.dispositions
                if d.candidate.semantic_subject == "composition.symmetry_mode"
                and d.candidate.classification == "requirement"
                and d.candidate.certainty == "explicit"
            ]
            if accepted_reaffirmations:
                assert all(d.outcome in {"KEPT", "NO_CHANGE"} for d in accepted_reaffirmations)
                plan = app.state.prompt_enrichment_service.restore_clarification_plan(
                    UUID(sid), UUID(org), UUID(state["clarification_plan_id"]), require_current=True
                )
                reaffirmation = next(
                    e
                    for e in plan.constraint_evidence
                    if e.source.message_id == message["message_id"]
                    and e.canonical_target == "composition.symmetry_mode"
                    and e.kind == "requirement"
                )
                assert reaffirmation.status == "superseded"
                assert reaffirmation.superseded_by_evidence_id == current_keep.evidence_id
            if text.endswith("in gold with an oval diamond."):
                revision = repo.get_current_revision(UUID(sid), UUID(org))
                assert revision.design.metal.material.value == "gold"
                assert revision.design.center_stone.shape.value == "oval"
                assert revision.design.center_stone.material.value == "diamond"
                assert revision.design.center_stone.shape.source.message_id == message["message_id"]
            snapshots[-1]["symmetry_decisions"] = [
                d.outcome
                for d in correction.correction_evaluation.dispositions
                if d.candidate.semantic_subject == "composition.symmetry_mode"
            ]
            snapshots[-1]["correction_outcome"] = correction.outcome
            assert repo.get_knowledge_release_pin(UUID(sid), UUID(org)) == binding
        before_restart = repo.list_enrichment_cycles(UUID(sid), UUID(org))
        assert provider.calls == []

    restarted, restored_app, restored_provider = _client(engine, config)
    with restarted:
        state_response = restarted.get(
            f"/v1/sessions/{sid}/prompt-enrichment/state", headers=headers
        )
        assert state_response.status_code == 200
        state = state_response.json()
        restored_repo = restored_app.state.prompt_enrichment_service.repository
        assert restored_repo.list_enrichment_cycles(UUID(sid), UUID(org)) == before_restart
        prompt = _finish_f00_lifecycle(
            restarted,
            restored_app,
            sid,
            org,
            headers,
            state,
            True,
            True,
            binding,
            (("composition.symmetry_mode", "preservation"),),
            initial["message_id"],
            any(
                e.status == "unresolved" and e.semantic_subject == "composition.symmetry_mode"
                for e in restored_app.state.prompt_enrichment_service.restore_clarification_plan(
                    UUID(sid), UUID(org), UUID(state["clarification_plan_id"]), require_current=True
                ).constraint_evidence
            ),
            preceding_cycles=1 + len(followups),
        )
        assert any(
            e["evidence_id"] == current_keep.evidence_id and e["status"] == "active"
            for e in prompt["constraint_evidence"]
        )
        final_keeps = [
            c
            for c in prompt["constraints"]
            if c["kind"] == "preservation" and c["target"] == "composition.symmetry_mode"
        ]
        assert len(final_keeps) == 1 and current_keep.evidence_id in final_keeps[0]["source_ids"]
        assert prompt["description"]["text"].count(current_keep.normalized_instruction) == 1
        assert restored_provider.calls == []
    fresh, fresh_app, fresh_provider = _client(engine, config)
    with fresh:
        final = fresh.get(f"/v1/sessions/{sid}/prompt-enrichment/final-output", headers=headers)
        assert final.status_code == 200 and final.json()["internal_final_prompt"] == prompt
        assert (
            fresh_app.state.prompt_enrichment_service.repository.get_knowledge_release_pin(
                UUID(sid), UUID(org)
            )
            == binding
        )
        assert fresh_provider.calls == []
    print(
        "F00_KEEP_TRACE "
        + json.dumps(
            {"followups": followups, "stages": snapshots, "final_ifp_keep": True},
            ensure_ascii=False,
        )
    )


F00_INDEPENDENT = (
    ("An asymmetric ring, no halo, without engraving.", True, False, True),
    (
        "An asymmetric ring, no halo, and without engraving — do not make it symmetrical.",
        True,
        True,
        True,
    ),
    ("An asymmetric ring without engraving.", True, False, False),
    ("An asymmetric ring, no halo, keep the band.", True, False, True),
)


@pytest.mark.parametrize(
    "text,symmetry,keep,halo", SCOPE_REVIEW_CASES + SCOPE_CONTROLS + F00_INDEPENDENT
)
def test_review_semantic_scope_http(engine, tmp_path, monkeypatch, text, symmetry, keep, halo):
    exercise_p010_rejected_http(
        engine, tmp_path, monkeypatch, text, symmetry=symmetry, keep=keep, halo=halo
    )


@pytest.mark.parametrize("text", REVIEW_NEGATIVES)
def test_review_false_positives_do_not_persist_across_restart(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text)


@pytest.mark.parametrize(
    "text",
    [
        "An asymmetric ring is not what I want — do not make it symmetrical.",
        "An asymmetric composition for the photograph — do not make it symmetrical.",
        "An asymmetric jewelry website design — do not make it symmetrical.",
        "An asymmetric ring photograph — do not make it symmetrical.",
    ],
)
def test_rejected_symmetry_cannot_activate_preservation(engine, tmp_path, monkeypatch, text):
    exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text)


def p010_bundle():
    # Test identity/report is synthetic. Original professional slice bytes/IDs
    # remain authentic. This does not qualify the actual extended DRAFT.
    core = json.loads((ROOT / "data/knowledge/v1/jewelry-core-1.0.0.json").read_text())
    fragment = json.loads((ROOT / "data/knowledge/v1_1/p010-symmetry-0.1.0.json").read_text())
    core.update(contract_version="1.1.0", package_id="jewelai.test.p010_raw_symmetry")
    for key in ("sources", "claims", "domain_knowledge", "language_mappings", "policies"):
        core[key].extend(fragment[key])
    return core


def exercise_p010_http(engine, tmp_path, monkeypatch):
    config, active, report = _release(tmp_path, bundle=p010_bundle())
    client, app, provider = _client(engine, config)
    observed = []
    from jewelai_parser import parse_full_message

    def observe(*args, **kwargs):
        result = parse_full_message(*args, **kwargs)
        observed.append(result)
        return result

    monkeypatch.setattr("jewelai_api.prompt_enrichment_runtime.parse_full_message", observe)
    with client:
        org, project, _ = create_hierarchy(client)
        response = client.post(
            f"/projects/{project}/sessions",
            headers={"X-Organization-ID": org},
            json={"role_id": "retail_client", "locale": "ru-RU"},
        )
        assert response.status_code == 201
        sid = response.json()["session_id"]
        headers = {"X-Organization-ID": org}
        # Existing authorized HTTP upgrade, empty state, no symmetry preseed.
        upgrade = client.post(
            f"/sessions/{sid}/schema-v1-1-upgrade",
            headers=headers,
            json={"expected_revision_id": response.json()["current_revision_id"]},
        )
        assert upgrade.status_code == 200, upgrade.json()
        assert upgrade.json()["design"]["composition"] is None
        text = "Асимметричное кольцо — не выравнивай его."
        original_message = _message(client, sid, org, text)
        initial = client.post(
            f"/v1/sessions/{sid}/prompt-enrichment/initial",
            headers=headers,
            json={
                "expected_revision_id": upgrade.json()["revision_id"],
                "message_id": original_message["message_id"],
            },
        )
        assert initial.status_code == 201, initial.json()
        repo = app.state.prompt_enrichment_service.repository
        revision = repo.get_current_revision(UUID(sid), UUID(org))
        symmetry = revision.design.composition.value.symmetry_mode
        assert symmetry.value == "asymmetrical" and not symmetry.confirmed and not symmetry.locked
        assert symmetry.source.message_id == original_message["message_id"]
        assert all(
            value is None
            for key, value in revision.design.composition.value.model_dump().items()
            if key != "symmetry_mode"
        )
        before_design = upgrade.json()["design"]
        after_design = revision.design.model_dump(mode="json")
        assert {
            key: value
            for key, value in after_design.items()
            if key not in {"composition", "jewelry_type"}
        } == {
            key: value
            for key, value in before_design.items()
            if key not in {"composition", "jewelry_type"}
        }
        assert observed[0].original_text == text
        assert any(
            c.semantic_subject == "composition.symmetry_mode"
            and c.normalization_source == "knowledge_library"
            for c in observed[0].candidates
        )
        binding = repo.get_knowledge_release_pin(UUID(sid), UUID(org))
        assert binding.binding.knowledge_contract_version == "1.1.0"
        assert binding.binding.runtime_sha256 == active.runtime_sha256
        assert binding.binding.validation_report_sha256 == report.sha256
        cycles_before = repo.list_enrichment_cycles(UUID(sid), UUID(org))
        assert len(cycles_before) == 1
        cell = next(
            c
            for c in cycles_before[0].result.final_matrix
            if c.target == "composition.symmetry_mode"
        )
        assert cell.value == "asymmetrical"
        assert set(cell.applicable_policy_ids) == {"STYLE-10-02", "STYLE-10-06", "STYLE-10-07"}
        assert provider.calls == []

    restarted, second_app, second_provider = _client(engine, config)
    with restarted:
        state_url = f"/v1/sessions/{sid}/prompt-enrichment/state"
        state = restarted.get(state_url, headers=headers)
        assert state.status_code == 200, state.json()
        correction_message = _message(
            restarted,
            sid,
            org,
            "A white or yellow gold ring with an oval sapphire center stone. No halo.",
        )
        correction = restarted.post(
            f"/v1/sessions/{sid}/prompt-enrichment/corrections",
            headers=headers,
            json={
                "expected_revision_id": state.json()["authoritative_revision_id"],
                "message_id": correction_message["message_id"],
            },
        )
        assert correction.status_code == 200, correction.json()
        current = correction.json()["state"]
        question = next(
            q
            for q in current["clarification_questions"]
            if any(o["value"] == "yellow" for o in q["options"])
        )
        answer_message = _message(restarted, sid, org, "yellow")
        answer = restarted.post(
            f"/v1/sessions/{sid}/prompt-enrichment/clarification-answers",
            headers=headers,
            json={
                "clarification_plan_id": current["clarification_plan_id"],
                "clarification_id": question["clarification_id"],
                "decision": "SELECT_OPTION",
                "selected_option": "yellow",
                "answer_id": str(uuid4()),
                "expected_revision_id": current["authoritative_revision_id"],
                "message_id": answer_message["message_id"],
            },
        )
        assert answer.status_code == 200, answer.json()
        final = restarted.get(f"/v1/sessions/{sid}/prompt-enrichment/final-output", headers=headers)
        assert final.status_code == 200, final.json()
        prompt = final.json()["internal_final_prompt"]
        assert prompt["schema_version"] == "2.1.0"
        fact = next(f for f in prompt["design_facts"] if f["target"] == "composition.symmetry_mode")
        assert fact["value"] == "asymmetrical" and not fact["confirmed"] and not fact["locked"]
        assert any(
            c["kind"] == "preservation" and c["target"] == "composition.symmetry_mode"
            for c in prompt["constraints"]
        )
        assert (
            repo.get_current_revision(UUID(sid), UUID(org)).design.composition.value.symmetry_mode
            == symmetry
        )
        assert repo.get_knowledge_release_pin(UUID(sid), UUID(org)) == binding
        assert second_provider.calls == []
        cycles = repo.list_enrichment_cycles(UUID(sid), UUID(org))
        assert len(cycles) == 3
        assert cycles[0].result == cycles_before[0].result
        for cycle in cycles:
            cell = next(
                c for c in cycle.result.final_matrix if c.target == "composition.symmetry_mode"
            )
            assert cell.value == "asymmetrical" and not cell.confirmed and not cell.locked
            assert set(cell.applicable_policy_ids) == {"STYLE-10-02", "STYLE-10-06", "STYLE-10-07"}
        raw = repo.get_message(UUID(sid), UUID(original_message["message_id"]), UUID(org))
        assert raw.content == text
        # A stale correction does not append a cycle or alter the selected release.
        stale = restarted.post(
            f"/v1/sessions/{sid}/prompt-enrichment/corrections",
            headers=headers,
            json={
                "expected_revision_id": upgrade.json()["revision_id"],
                "message_id": correction_message["message_id"],
            },
        )
        assert stale.status_code == 409
        assert repo.list_enrichment_cycles(UUID(sid), UUID(org)) == cycles
    third, third_app, third_provider = _client(engine, config)
    with third:
        restored = third.get(f"/v1/sessions/{sid}/prompt-enrichment/final-output", headers=headers)
        assert restored.status_code == 200, restored.json()
        assert restored.json()["internal_final_prompt"] == prompt
        state = third.get(f"/v1/sessions/{sid}/prompt-enrichment/state", headers=headers)
        assert state.status_code == 200
        plan = third_app.state.prompt_enrichment_service.restore_clarification_plan(
            UUID(sid), UUID(org), UUID(state.json()["clarification_plan_id"]), require_current=True
        )
        assert any(e.original_wording == "не выравнивай его" for e in plan.constraint_evidence)
        assert third_provider.calls == []
        third.headers["Authorization"] = "Bearer test-unrelated"
        denied = third.get(f"/v1/sessions/{sid}/prompt-enrichment/state", headers=headers)
        assert denied.status_code in {403, 404}
    assert app is not second_app
    return sid, org


def test_original_t10_10_raw_http_lifecycle(engine, tmp_path, monkeypatch):
    exercise_p010_http(engine, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "mode",
    [
        "absent",
        "unknown",
        "known_empty",
        "confirmed",
        "locked",
        "parent_locked",
        "not_applicable",
        "child_not_applicable",
        "forged_evidence",
    ],
)
def test_p010_consumer_respects_actual_canonical_authority(tmp_path, mode):
    from jewelai_domain import load_domain_dictionary
    from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1
    from jewelai_domain.models import (
        DesignRevision,
        Explicit,
        MessageSource,
        NotApplicable,
        Unknown,
    )
    from jewelai_domain.models_v1_1 import (
        CompositionV1_1,
        DesignRevisionV1_1,
        upgrade_design_revision_v1_to_v1_1,
    )
    from jewelai_parser import parse_full_message
    from jewelai_prompts import load_prompt_templates

    from jewelai_api.parsed_enrichment import (
        enrich_parsed_candidates_with_active_release,
        proposed_design_for_transition,
    )

    config, active, report = _release(tmp_path, bundle=p010_bundle())
    revision = upgrade_design_revision_v1_to_v1_1(
        DesignRevision.model_validate_json(
            (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_bytes()
        )
    )
    source = MessageSource(message_id=str(uuid4()), recorded_at=revision.created_at)
    composition = None
    if mode == "unknown":
        composition = Unknown()
    elif mode == "not_applicable":
        composition = NotApplicable(reason="Test applicability decision", source=source)
    elif mode not in {"absent", "forged_evidence"}:
        symmetry = None
        if mode == "child_not_applicable":
            symmetry = NotApplicable(reason="Test applicability decision", source=source)
        elif mode != "known_empty":
            symmetry = Explicit[str](
                value="symmetrical",
                source=source,
                confirmed=mode in {"confirmed", "locked"},
                locked=mode == "locked",
            )
        composition = Explicit[CompositionV1_1](
            value=CompositionV1_1(symmetry_mode=symmetry),
            source=source,
            confirmed=mode == "parent_locked",
            locked=mode == "parent_locked",
        )
    payload = revision.model_dump(mode="json")
    payload["design"]["composition"] = composition.model_dump(mode="json") if composition else None
    revision = DesignRevisionV1_1.model_validate(payload)
    before = revision.model_dump_json()
    dictionary = load_domain_dictionary(ROOT / "data/dictionary/v1.0.0.json")
    parsed = parse_full_message(
        "Асимметричное кольцо — не выравнивай его.",
        locale="ru",
        dictionary=dictionary,
        knowledge_runtime=active.compiled_runtime,
    )
    if mode == "forged_evidence":
        parsed = parsed.model_copy(
            update={
                "candidates": tuple(
                    c.model_copy(update={"detail": "forged binding"})
                    if c.normalization_source == "knowledge_library"
                    else c
                    for c in parsed.candidates
                )
            }
        )
    evaluation = enrich_parsed_candidates_with_active_release(
        revision,
        parse_result=parsed,
        source=source,
        dictionary=dictionary,
        templates=load_prompt_templates(ROOT / "data/prompts/v1.0.0.json"),
        artifact_store=KnowledgeArtifactStoreV1_1(config.artifact_root),
        knowledge_package_id=active.package_id,
        knowledge_artifact_version=str(active.artifact_version),
        active_release=active,
        validation_report=report,
    )
    design = proposed_design_for_transition(revision, evaluation)
    if mode in {"absent", "unknown", "known_empty"}:
        assert design.composition.value.symmetry_mode.value == "asymmetrical"
        assert not design.composition.value.symmetry_mode.confirmed
        assert not design.composition.value.symmetry_mode.locked
    else:
        assert design.composition == revision.design.composition
    assert revision.model_dump_json() == before
