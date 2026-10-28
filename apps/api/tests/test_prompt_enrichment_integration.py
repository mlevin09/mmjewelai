"""Controlled HTTP integration evidence for Prompt Enrichment Step #13.

The application factory remains unchanged: these tests opt in by explicitly injecting the real
runtime service.  External text-understanding and generation providers must never be called.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from conftest import NOW, create_hierarchy
from jewelai_parser import parse_full_message
from jewelai_persistence import Base, create_database_engine, create_session_factory
from jewelai_persistence.models import ClarificationPlanRow, EnrichmentCycleRow
from jewelai_prompts import CanonicalInternalFinalPrompt as InternalFinalPrompt
from jewelai_prompts import FinalPromptConstraintEvidence
from sqlalchemy import func, select
from test_persistence import build_service
from test_prompt_enrichment_http import _client, _message
from test_prompt_enrichment_runtime import _runtime

from jewelai_api.prompt_enrichment_runtime import PromptEnrichmentRuntimeService


def _restart_runtime(service, runtime, store, active, report):
    return PromptEnrichmentRuntimeService(
        service.repository,
        service.artifacts,
        store,
        knowledge_package_id=runtime.knowledge_package_id,
        knowledge_artifact_version=runtime.knowledge_artifact_version,
        active_release=active,
        validation_report=report,
        clock=lambda: NOW,
        uuid_factory=uuid4,
    )


def _release_payload(runtime):
    return {
        "package_id": runtime.knowledge_package_id,
        "artifact_version": runtime.knowledge_artifact_version,
        "runtime_sha256": runtime.active_release.runtime_sha256,
        "validation_report_sha256": runtime.active_release.validation_report_sha256,
    }


def _exercise_halo_constraint_sequence(
    engine, tmp_path, role_id, locale, sequence, *, initial_center_fields=("shape",)
):
    """Exercise real HTTP/CAS and durable restoration with synthetic, explicitly sourced facts."""
    service = build_service(engine)
    runtime, store, active, report = _runtime(service, tmp_path)
    client, provider = _client(engine, runtime)
    trace = []
    with client:
        org, _, session_response = create_hierarchy(client, role_id=role_id, locale=locale)
        session = session_response.json()
        sid = session["session_id"]
        headers = {"X-Organization-ID": org}
        current = service.repository.get_current_revision(UUID(sid), UUID(org))
        # Existing test_rules dimensions fixture, never inferred from a qualitative request.
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
            if field == "shape" and sequence[0][0].startswith("Design a platinum"):
                # Test A must exercise an actual new oval revision, not a prefilled value.
                continue
            design[component][field] = {
                "availability": "value",
                "origin": "explicit",
                "value": value,
                "source": source,
                "confirmed": False,
                "locked": False,
            }
        setup = client.post(
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
        assert setup.status_code == 200, setup.json()
        for action in ("confirm", "lock"):
            current = service.repository.get_current_revision(UUID(sid), UUID(org))
            response = client.post(
                f"/sessions/{sid}/revisions",
                headers=headers,
                json={
                    "action": action,
                    "expected_revision_id": str(current.revision_id),
                    "target": "center_stone.dimensions",
                    "source": source,
                    "reason": "Protect explicit fixture dimensions",
                },
            )
            assert response.status_code == 200, response.json()

        previous = ()
        saved_plans = {}
        for number, (text, expected_kind, expected_wording) in enumerate(sequence, 1):
            before = service.repository.get_current_revision(UUID(sid), UUID(org))
            message = _message(client, sid, org, text)
            payload = {
                "expected_revision_id": str(before.revision_id),
                "message_id": message["message_id"],
            }
            route = "initial" if number == 1 else "corrections"
            response = client.post(
                f"/v1/sessions/{sid}/prompt-enrichment/{route}", headers=headers, json=payload
            )
            assert response.status_code == (201 if number == 1 else 200), response.json()
            state = runtime.get_current_state(UUID(sid), UUID(org))
            current = service.repository.get_current_revision(UUID(sid), UUID(org))
            # The combined collision case also explicitly supplies the initially
            # unknown material. Later turns must preserve it along with all other facts.
            allowed = set(initial_center_fields) if number == 1 else {"shape"}
            assert current.design.center_stone.model_dump(
                exclude=allowed
            ) == before.design.center_stone.model_dump(exclude=allowed)
            assert current.design.construction == before.design.construction
            if number == 2 and sequence[0][0].startswith("Design a platinum"):
                assert before.design.center_stone.shape is None
                assert current.design.center_stone.shape.value == "oval"
                assert current.parent_revision_id == before.revision_id
                assert current.design.metal == before.design.metal
                assert response.json()["outcome"] == "APPLIED"
            elif number > 1:
                assert current.design == before.design
            assert state.enrichment_cycle_number == number
            halo = tuple(
                item
                for item in state.clarification_plan.constraint_evidence
                if item.semantic_subject == "feature.halo"
            )
            assert len(halo) == number
            latest = [item for item in halo if item.status == "active"]
            assert len(latest) == 1
            latest = latest[0]
            assert latest.kind == expected_kind
            assert latest.original_wording == expected_wording
            assert latest.source.message_id == message["message_id"]
            assert latest.session_id == UUID(sid) and latest.organization_id == UUID(org)
            assert latest.source_revision_id == current.revision_id
            assert latest.source_enrichment_cycle_id == state.enrichment_cycle_id
            assert text[latest.source_span_start : latest.source_span_end] == expected_wording
            normalized = (
                ("Do not include a halo." if expected_kind == "prohibition" else "Include a halo.")
                if locale == "en"
                else ("Не добавлять гало." if expected_kind == "prohibition" else "Добавить гало.")
            )
            assert latest.normalized_instruction == normalized
            for item in halo:
                assert (
                    FinalPromptConstraintEvidence.model_validate_json(item.model_dump_json())
                    == item
                )
            by_id = {item.evidence_id: item for item in halo}
            for old in previous:
                retained = by_id[old.evidence_id]
                assert retained.source == old.source
                assert retained.original_wording == old.original_wording
                if old.status == "superseded":
                    assert retained == old
                else:
                    assert retained.status == "superseded"
                    assert retained.superseded_by_evidence_id == latest.evidence_id
            prompt = state.final_output.internal_final_prompt
            assert InternalFinalPrompt.model_validate_json(prompt.model_dump_json()) == prompt
            authoritative_halo = [
                item for item in prompt.constraints if item.target == "feature.halo"
            ]
            assert len(authoritative_halo) == 1 and authoritative_halo[0].kind == expected_kind
            assert authoritative_halo[0].instruction == normalized
            assert prompt.product_state_revision_id == current.revision_id
            final = client.get(
                f"/v1/sessions/{sid}/prompt-enrichment/final-output", headers=headers
            )
            # Preserve the existing HTTP contract: clarification statuses can expose a
            # diagnostically BLOCKED prompt with 200. Do not mistake it for READY or fix
            # general readiness/routing in this polarity regression.
            assert final.status_code == (
                409 if state.status.value == "final_output_blocked" else 200
            )
            if final.status_code == 200:
                assert final.json()["internal_final_prompt"] == prompt.model_dump(mode="json")
            if number == 1 and before.design.center_stone.shape is not None:
                assert final.status_code == 200  # Real fixture requiredness, not forced readiness.
            if number > 1:
                # This HTTP wrapper rebuilds lineage from the latest cycle on replay. Its
                # existing conflict response must fail closed, not append duplicate evidence.
                retry = client.post(
                    f"/v1/sessions/{sid}/prompt-enrichment/{route}", headers=headers, json=payload
                )
                assert retry.status_code == 409
                assert retry.json()["error"] in {"correction_conflict", "stale_revision"}
                assert runtime.get_current_state(UUID(sid), UUID(org)) == state
            plans = service.repository.list_clarification_plans(UUID(sid), UUID(org))
            current_plans = {item.clarification_plan_id: item for item in plans}
            assert all(current_plans[key] == value for key, value in saved_plans.items())
            saved_plans = current_plans
            parsed = parse_full_message(
                text,
                locale=locale,
                dictionary=service.artifacts.dictionary,
                knowledge_runtime=active.compiled_runtime,
            )
            trace.append(
                {
                    "text": text,
                    "message_id": message["message_id"],
                    "response": response.json(),
                    "parse_result": parsed.model_dump(mode="json"),
                    "revision": current.model_dump(mode="json"),
                    "workflow": state.model_dump(mode="json"),
                    "final_output_http": final.status_code,
                }
            )
            restored = _restart_runtime(build_service(engine), runtime, store, active, report)
            assert restored.get_current_state(UUID(sid), UUID(org)) == state
            previous = halo
        locked_before = service.repository.get_current_revision(UUID(sid), UUID(org))
        message = _message(
            client, sid, org, "Center stone dimensions 10 x 8 x 5 mm. Do not add a halo."
        )
        response = client.post(
            f"/v1/sessions/{sid}/prompt-enrichment/corrections",
            headers=headers,
            json={
                "expected_revision_id": str(locked_before.revision_id),
                "message_id": message["message_id"],
            },
        )
        assert response.status_code == 200 and response.json()["outcome"] == "REJECTED"
        assert service.repository.get_current_revision(UUID(sid), UUID(org)) == locked_before
        assert provider.calls == []
        foreign = service.create_organization("Other synthetic scope")
        assert (
            client.get(
                f"/v1/sessions/{sid}/prompt-enrichment/state",
                headers={"X-Organization-ID": str(foreign.organization_id)},
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/v1/sessions/{sid}/prompt-enrichment/state",
                headers={**headers, "Authorization": ""},
            ).status_code
            == 401
        )
    return {
        "role_id": role_id,
        "locale": locale,
        "session_id": sid,
        "organization_id": org,
        "turns": trace,
    }


HALO_SEQUENCES = [
    (
        "en",
        (
            ("Design a platinum engagement ring. No halo.", "prohibition", "No halo"),
            ("Make the center stone oval. Do not add a halo.", "prohibition", "Do not add a halo"),
            (
                "Keep the platinum ring and don't include a halo.",
                "prohibition",
                "don't include a halo",
            ),
        ),
    ),
    (
        "en",
        (
            ("No halo.", "prohibition", "No halo"),
            ("Actually, add a halo.", "requirement", "add a halo"),
            ("I changed my mind. Do not add a halo.", "prohibition", "Do not add a halo"),
        ),
    ),
    (
        "ru",
        (
            ("Без гало.", "prohibition", "Без гало"),
            ("Не добавляйте гало.", "prohibition", "Не добавляйте гало"),
            ("Не хочу гало.", "prohibition", "Не хочу гало"),
        ),
    ),
    (
        "ru",
        (
            ("Без halo.", "prohibition", "Без halo"),
            ("Do not add гало.", "prohibition", "Do not add гало"),
            ("Не добавлять halo.", "prohibition", "Не добавлять halo"),
        ),
    ),
]


@pytest.mark.parametrize("role_id", ["retail_client", "jewelry_designer"])
@pytest.mark.parametrize(("locale", "sequence"), HALO_SEQUENCES)
def test_halo_negation_and_polarity_changes_preserve_durable_lineage(
    engine, tmp_path, role_id, locale, sequence
):
    _exercise_halo_constraint_sequence(engine, tmp_path, role_id, locale, sequence)


def test_full_http_cycle_restores_retries_corrects_and_preserves_authority(engine, tmp_path):
    service = build_service(engine)
    runtime, store, active, report = _runtime(service, tmp_path)
    first_client, first_legacy_provider = _client(engine, runtime)
    request_text = (
        "A white or yellow-gold engagement ring with an oval sapphire center stone, "
        "two small diamonds on each side, and no halo."
    )

    with first_client:
        organization_id, _, session_response = create_hierarchy(first_client)
        session = session_response.json()
        session_id = session["session_id"]
        message = _message(first_client, session_id, organization_id, request_text)
        initial = first_client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert initial.status_code == 201, initial.json()
        initial_state = initial.json()
        assert initial_state["knowledge_release"] == _release_payload(runtime)
        assert initial_state["enrichment_cycle_number"] == 1
        assert initial_state["clarification_plan_id"]
        assert initial_state["clarification_plan_content_hash"]
        assert first_legacy_provider.calls == []

    initial_durable = runtime.get_current_state(UUID(session_id), UUID(organization_id))
    initial_constraints = initial_durable.clarification_plan.constraint_evidence
    assert len(initial_constraints) == 1
    assert initial_constraints[0].kind == "prohibition"
    assert initial_constraints[0].status == "active"
    assert initial_constraints[0].semantic_subject == "feature.halo"
    assert initial_constraints[0].original_wording == "no halo"

    original_revision = service.repository.get_current_revision(
        UUID(session_id), UUID(organization_id)
    )
    assert original_revision.design.metal.color is None
    assert original_revision.design.center_stone.shape.value == "oval"
    # The parser retains the evidence but cannot invent a stable repeated-field group.
    assert original_revision.design.side_stones == ()

    restarted_service = build_service(engine)
    restarted = _restart_runtime(restarted_service, runtime, store, active, report)
    second_client, second_legacy_provider = _client(engine, restarted)
    with second_client:
        restored = second_client.get(
            f"/v1/sessions/{session_id}/prompt-enrichment/state",
            headers={"X-Organization-ID": organization_id},
        )
        assert restored.status_code == 200
        assert restored.json() == initial_state

        question = next(
            item
            for item in restored.json()["clarification_questions"]
            if any(option["value"] == "yellow" for option in item["options"])
        )
        selected = next(option for option in question["options"] if option["value"] == "yellow")
        answer_message = _message(
            second_client,
            session_id,
            organization_id,
            selected["value"],
        )
        answer_payload = {
            "clarification_plan_id": initial_state["clarification_plan_id"],
            "clarification_id": question["clarification_id"],
            "decision": "SELECT_OPTION",
            "selected_option": selected["value"],
            "expected_revision_id": initial_state["authoritative_revision_id"],
            "answer_id": str(uuid4()),
            "message_id": answer_message["message_id"],
        }
        answered = second_client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/clarification-answers",
            headers={"X-Organization-ID": organization_id},
            json=answer_payload,
        )
        assert answered.status_code == 200, answered.json()
        answered_body = answered.json()
        assert answered_body["state"]["knowledge_release"] == _release_payload(runtime)
        assert answered_body["state"]["enrichment_cycle_number"] == 2
        assert second_legacy_provider.calls == []

    restarted_again_service = build_service(engine)
    restarted_again = _restart_runtime(restarted_again_service, runtime, store, active, report)
    third_client, third_legacy_provider = _client(engine, restarted_again)
    with third_client:
        retry = third_client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/clarification-answers",
            headers={"X-Organization-ID": organization_id},
            json=answer_payload,
        )
        assert retry.status_code == 200
        assert retry.json() == answered_body

        conflicting = third_client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/clarification-answers",
            headers={"X-Organization-ID": organization_id},
            json={
                **answer_payload,
                "answer_id": str(uuid4()),
                "selected_option": "white",
            },
        )
        assert conflicting.status_code == 409
        assert conflicting.json()["error"] == "clarification_conflict"

        correction_message = _message(
            third_client,
            session_id,
            organization_id,
            "Change the center stone to emerald cut, but keep the yellow gold. No halo.",
        )
        correction = third_client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/corrections",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": answered_body["state"]["authoritative_revision_id"],
                "message_id": correction_message["message_id"],
            },
        )
        assert correction.status_code == 200, correction.json()
        corrected = correction.json()["state"]
        assert corrected["knowledge_release"] == _release_payload(runtime)
        assert corrected["enrichment_cycle_number"] == 3
        assert third_legacy_provider.calls == []

        final = third_client.get(
            f"/v1/sessions/{session_id}/prompt-enrichment/final-output",
            headers={"X-Organization-ID": organization_id},
        )
        assert final.status_code == 200, final.json()
        output = final.json()
        prompt = output["internal_final_prompt"]
        assert prompt["schema_version"] == "2.0.0"
        assert prompt["product_state_revision_id"] == corrected["authoritative_revision_id"]
        assert prompt["knowledge_release"] == _release_payload(runtime)
        assert prompt["description_content_hash"] == output["description"]["content_hash"]
        assert "oval" not in output["description"]["text"].casefold()
        assert "Do not include a halo" in prompt["prompt_text"]
        assert "Do not include a halo" in output["description"]["text"]
        halo_constraints = [
            item for item in prompt["constraints"] if item["target"] == "feature.halo"
        ]
        assert len(halo_constraints) == 1
        assert halo_constraints[0]["kind"] == "prohibition"
        halo_evidence = [
            item
            for item in prompt["constraint_evidence"]
            if item["semantic_subject"] == "feature.halo"
        ]
        assert [item["status"] for item in halo_evidence].count("active") == 1
        assert [item["status"] for item in halo_evidence].count("superseded") == 1
        assert "google" not in prompt["prompt_text"].casefold()
        assert "openai" not in prompt["prompt_text"].casefold()

        stale_message = _message(
            third_client,
            session_id,
            organization_id,
            "Change the center stone back to oval.",
        )
        stale_correction = third_client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/corrections",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": initial_state["authoritative_revision_id"],
                "message_id": stale_message["message_id"],
            },
        )
        assert stale_correction.status_code == 409
        assert stale_correction.json()["error"] == "stale_revision"

    durable_state = restarted_again.get_current_state(UUID(session_id), UUID(organization_id))
    assert any(
        item.disposition_reason.value == "prohibition_retained"
        for item in durable_state.clarification_plan.unasked_evidence
    )

    corrected_revision = service.repository.get_current_revision(
        UUID(session_id), UUID(organization_id)
    )
    assert corrected_revision.design.center_stone.shape.value == "emerald_cut"
    assert corrected_revision.design.metal.color.value == "yellow"
    assert corrected_revision.design.side_stones == ()
    assert (
        len(service.repository.list_clarification_answers(UUID(session_id), UUID(organization_id)))
        == 1
    )
    assert (
        len(service.repository.list_enrichment_cycles(UUID(session_id), UUID(organization_id))) == 3
    )
    assert (
        len(service.repository.list_clarification_plans(UUID(session_id), UUID(organization_id)))
        == 3
    )


@pytest.mark.parametrize(
    ("locale", "text", "expected_color", "expected_shape"),
    (
        (
            "ru",
            "Хочу кольцо из жёлтого золота с овальным сапфиром в центре. Без гало.",
            None,
            None,
        ),
        (
            "ru",
            "Хочу yellow-gold кольцо with an oval sapphire в центре. Без гало.",
            None,
            None,
        ),
        (
            "en",
            "I want a yellow-gold ring with an oval sapphire center stone and no halo.",
            "yellow",
            "oval",
        ),
    ),
)
def test_http_initial_flow_is_internal_bilingual_and_provider_independent(
    engine, tmp_path, locale, text, expected_color, expected_shape
):
    service = build_service(engine)
    runtime, *_ = _runtime(service, tmp_path)
    client, legacy_provider = _client(engine, runtime)
    with client:
        organization_id, _, session_response = create_hierarchy(client, locale=locale)
        session = session_response.json()
        message = _message(client, session["session_id"], organization_id, text)
        response = client.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert response.status_code == 201, response.json()
        assert response.json()["description"]["locale"] == locale
        assert legacy_provider.calls == []

    revision = service.repository.get_current_revision(
        UUID(session["session_id"]), UUID(organization_id)
    )
    assert (
        revision.design.metal.color.value if revision.design.metal.color is not None else None
    ) == expected_color
    assert (
        revision.design.center_stone.shape.value
        if revision.design.center_stone.shape is not None
        else None
    ) == expected_shape
    # The persisted message is the only source text; the controlled path does not call the legacy
    # Google text-understanding adapter even when deterministic parsing cannot safely normalize an
    # inflected RU term into canonical Product State.
    persisted = service.repository.get_message(
        UUID(session["session_id"]), UUID(message["message_id"]), UUID(organization_id)
    )
    assert persisted.content == text
    durable = runtime.get_current_state(UUID(session["session_id"]), UUID(organization_id))
    prohibition = next(
        item
        for item in durable.clarification_plan.constraint_evidence
        if item.semantic_subject == "feature.halo" and item.status == "active"
    )
    assert prohibition.kind == "prohibition"
    assert prohibition.original_wording.casefold() in {"no halo", "без гало", "без halo"}
    assert prohibition.normalized_instruction == (
        "Не добавлять гало." if locale == "ru" else "Do not include a halo."
    )


def test_http_contract_rejects_client_release_authority_and_exposes_routes_only_when_injected(
    engine, tmp_path
):
    service = build_service(engine)
    runtime, *_ = _runtime(service, tmp_path)
    controlled, _ = _client(engine, runtime)
    default, _ = _client(engine)

    controlled_schema = controlled.get("/openapi.json").json()
    default_schema = default.get("/openapi.json").json()
    path = "/v1/sessions/{session_id}/prompt-enrichment/initial"
    assert path in controlled_schema["paths"]
    assert path not in default_schema["paths"]

    with controlled:
        organization_id, _, session_response = create_hierarchy(controlled)
        session = session_response.json()
        message = _message(
            controlled, session["session_id"], organization_id, "I want an oval ring."
        )
        response = controlled.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
                "knowledge_release": {"package_id": "client-controlled"},
            },
        )
        assert response.status_code == 422


def test_legacy_cycle_without_durable_plan_fails_closed_without_reconstruction(engine, tmp_path):
    service = build_service(engine)
    runtime, store, active, report = _runtime(service, tmp_path)
    client, _ = _client(engine, runtime)
    with client:
        organization_id, _, session_response = create_hierarchy(client)
        session = session_response.json()
        message = _message(client, session["session_id"], organization_id, "I want an oval ring.")
        initial = client.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert initial.status_code == 201

    with create_session_factory(engine).begin() as db:
        db.delete(
            db.get(
                ClarificationPlanRow,
                UUID(initial.json()["clarification_plan_id"]),
            )
        )

    restarted_service = build_service(engine)
    restarted = _restart_runtime(restarted_service, runtime, store, active, report)
    restarted_client, _ = _client(engine, restarted)
    with restarted_client:
        response = restarted_client.get(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/state",
            headers={"X-Organization-ID": organization_id},
        )
    assert response.status_code == 500
    assert response.json()["error"] == "invalid_durable_history"


def test_http_state_fails_closed_when_pinned_active_release_no_longer_matches(engine, tmp_path):
    service = build_service(engine)
    runtime, *_ = _runtime(service, tmp_path)
    client, _ = _client(engine, runtime)
    with client:
        organization_id, _, session_response = create_hierarchy(client)
        session = session_response.json()
        message = _message(client, session["session_id"], organization_id, "I want an oval ring.")
        initial = client.post(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert initial.status_code == 201

        runtime.active_release = runtime.active_release.model_copy(
            update={"runtime_sha256": "0" * 64}
        )
        state = client.get(
            f"/v1/sessions/{session['session_id']}/prompt-enrichment/state",
            headers={"X-Organization-ID": organization_id},
        )

    assert state.status_code == 503, state.json()
    assert state.json()["error"] == "knowledge_release_unavailable"


@pytest.mark.postgres
def test_postgres_http_concurrent_initial_requests_commit_one_complete_history(tmp_path):
    database_url = os.getenv("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL concurrency coverage")
    engine = create_database_engine(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        service = build_service(engine)
        runtime, *_ = _runtime(service, tmp_path)
        setup_client, _ = _client(engine, runtime)
        with setup_client:
            organization_id, _, session_response = create_hierarchy(setup_client)
            session = session_response.json()
            message = _message(
                setup_client,
                session["session_id"],
                organization_id,
                "I want a yellow-gold ring with an oval center stone.",
            )

        payload = {
            "expected_revision_id": session["current_revision_id"],
            "message_id": message["message_id"],
        }

        def start_once():
            client, _ = _client(engine, runtime)
            with client:
                return client.post(
                    f"/v1/sessions/{session['session_id']}/prompt-enrichment/initial",
                    headers={"X-Organization-ID": organization_id},
                    json=payload,
                ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(lambda _: start_once(), range(2)))

        assert statuses == [201, 409]
        scoped_session_id = UUID(session["session_id"])
        scoped_organization_id = UUID(organization_id)
        assert (
            len(
                service.repository.list_enrichment_cycles(scoped_session_id, scoped_organization_id)
            )
            == 1
        )
        assert (
            len(
                service.repository.list_clarification_plans(
                    scoped_session_id, scoped_organization_id
                )
            )
            == 1
        )
        with create_session_factory(engine)() as db:
            assert db.scalar(select(func.count()).select_from(EnrichmentCycleRow)) == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
