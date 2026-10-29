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


def exercise_p010_rejected_http(engine, tmp_path, monkeypatch, text):
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
        assert revision.design.composition is None
        # Existing parser may retain the explicitly mentioned product category;
        # no composition or unrelated design facts may be invented.
        assert {
            key: value
            for key, value in revision.design.model_dump(mode="json").items()
            if key != "jewelry_type"
        } == {
            key: value for key, value in upgrade.json()["design"].items() if key != "jewelry_type"
        }
        assert observed[0].original_text == text
        assert observed[0].knowledge_runtime_sha256 == active.runtime_sha256
        assert not any(
            c.semantic_subject == "composition.symmetry_mode"
            and c.classification == "requirement"
            and c.certainty == "explicit"
            for c in observed[0].candidates
        )
        cycles = repo.list_enrichment_cycles(UUID(sid), UUID(org))
        assert len(cycles) == 1
        assert not any(
            d.outcome == "APPLIED" and d.target in {"composition", "composition.symmetry_mode"}
            for d in cycles[0].result.decisions
        )
        binding = repo.get_knowledge_release_pin(UUID(sid), UUID(org))
        assert binding.binding.runtime_sha256 == active.runtime_sha256
        assert binding.binding.validation_report_sha256 == report.sha256
        assert repo.get_message(UUID(sid), UUID(message["message_id"]), UUID(org)).content == text
        state = client.get(f"/v1/sessions/{sid}/prompt-enrichment/state", headers=headers)
        assert state.status_code == 200
        plan = app.state.prompt_enrichment_service.restore_clarification_plan(
            UUID(sid), UUID(org), UUID(state.json()["clarification_plan_id"]), require_current=True
        )
        assert not any(
            e.semantic_subject == "composition.symmetry_mode"
            and e.kind == "preservation"
            and e.status == "active"
            for e in plan.constraint_evidence
        )
        assert provider.calls == []
        revision_url = f"/sessions/{sid}/revisions/{revision.revision_id}"
        persisted = client.get(revision_url, headers=headers)
        assert persisted.status_code == 200
        assert persisted.json()["design"] == revision.design.model_dump(mode="json")

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
