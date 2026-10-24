"""Controlled HTTP integration evidence for Prompt Enrichment Step #13.

The application factory remains unchanged: these tests opt in by explicitly injecting the real
runtime service.  External text-understanding and generation providers must never be called.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from conftest import NOW, create_hierarchy
from jewelai_persistence import Base, create_database_engine, create_session_factory
from jewelai_persistence.models import ClarificationPlanRow, EnrichmentCycleRow
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
        assert final.status_code in {200, 409}
        if final.status_code == 200:
            output = final.json()
            prompt = output["internal_final_prompt"]
            assert prompt["product_state_revision_id"] == corrected["authoritative_revision_id"]
            assert prompt["knowledge_release"] == _release_payload(runtime)
            assert prompt["description_content_hash"] == output["description"]["content_hash"]
            assert "oval" not in output["description"]["text"].casefold()
            assert "google" not in prompt["prompt_text"].casefold()
            assert "openai" not in prompt["prompt_text"].casefold()
        else:
            assert final.json()["error"] == "final_output_not_ready"

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
