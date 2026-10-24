from uuid import uuid4

from conftest import (
    NOW,
    ROOT,
    FakeAssetAccessSigner,
    FakeGenerationTaskPublisher,
    FakePrivateObjectStore,
    FakeTextUnderstandingProvider,
    FakeTokenVerifier,
    create_hierarchy,
)
from fastapi.testclient import TestClient
from test_persistence import build_service
from test_prompt_enrichment_runtime import _runtime

from jewelai_api import create_app
from jewelai_api.settings import RuntimeSettings


def _client(engine, runtime=None):
    text_provider = FakeTextUnderstandingProvider()
    application = create_app(
        RuntimeSettings(database_url="sqlite+pysqlite://", repository_root=ROOT),
        engine=engine,
        clock=lambda: NOW,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=FakeAssetAccessSigner(),
        asset_object_store=FakePrivateObjectStore(),
        generation_task_publisher=FakeGenerationTaskPublisher(),
        text_understanding_provider=text_provider,
        prompt_enrichment_service=runtime,
    )
    client = TestClient(application)
    client.headers["Authorization"] = "Bearer test-owner-a"
    return client, text_provider


def _message(client, session_id, organization_id, content):
    response = client.post(
        f"/sessions/{session_id}/messages",
        headers={"X-Organization-ID": organization_id},
        json={"content": content},
    )
    assert response.status_code == 201
    return response.json()


def test_new_router_is_disabled_by_default_and_legacy_routes_are_unchanged(engine):
    client, text_provider = _client(engine)
    with client:
        organization_id, _, session = create_hierarchy(client)
        session_id = session.json()["session_id"]

        assert client.get("/health").json() == {"status": "ok"}
        assert (
            client.get(
                f"/sessions/{session_id}", headers={"X-Organization-ID": organization_id}
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/v1/sessions/{session_id}/prompt-enrichment/state",
                headers={"X-Organization-ID": organization_id},
            ).status_code
            == 404
        )
        assert text_provider.calls == []


def test_controlled_http_flow_restores_plan_and_processes_answer(engine, tmp_path):
    internal_service = build_service(engine)
    runtime, *_ = _runtime(internal_service, tmp_path)
    client, text_provider = _client(engine, runtime)
    with client:
        organization_id, _, session_response = create_hierarchy(client)
        session = session_response.json()
        session_id = session["session_id"]
        message = _message(
            client,
            session_id,
            organization_id,
            "I want a white or yellow gold ring.",
        )

        initial = client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/initial",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": session["current_revision_id"],
                "message_id": message["message_id"],
            },
        )
        assert initial.status_code == 201
        body = initial.json()
        assert body["clarification_plan_id"]
        question = next(item for item in body["clarification_questions"] if item["options"])
        state = client.get(
            f"/v1/sessions/{session_id}/prompt-enrichment/state",
            headers={"X-Organization-ID": organization_id},
        )
        assert state.status_code == 200
        assert (
            state.json()["clarification_plan_content_hash"]
            == body["clarification_plan_content_hash"]
        )

        answer_message = _message(
            client,
            session_id,
            organization_id,
            question["options"][0]["value"],
        )
        payload = {
            "clarification_plan_id": body["clarification_plan_id"],
            "clarification_id": question["clarification_id"],
            "decision": "SELECT_OPTION",
            "selected_option": question["options"][0]["value"],
            "expected_revision_id": body["authoritative_revision_id"],
            "answer_id": str(uuid4()),
            "message_id": answer_message["message_id"],
        }
        invalid_option = client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/clarification-answers",
            headers={"X-Organization-ID": organization_id},
            json={**payload, "selected_option": "not-an-offered-value"},
        )
        assert invalid_option.status_code == 422
        assert invalid_option.json()["error"] == "invalid_clarification_option"
        answered = client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/clarification-answers",
            headers={"X-Organization-ID": organization_id},
            json=payload,
        )
        assert answered.status_code == 200
        answered_body = answered.json()
        assert answered_body["outcome"] == "APPLIED"
        assert answered_body["state"]["enrichment_cycle_number"] == 2
        assert answered_body["state"]["clarification_plan_id"] != body["clarification_plan_id"]

        retry = client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/clarification-answers",
            headers={"X-Organization-ID": organization_id},
            json=payload,
        )
        assert retry.status_code == 200
        assert retry.json()["answer_content_hash"] == answered_body["answer_content_hash"]

        correction_message = _message(
            client,
            session_id,
            organization_id,
            "Make the center stone oval.",
        )
        correction = client.post(
            f"/v1/sessions/{session_id}/prompt-enrichment/corrections",
            headers={"X-Organization-ID": organization_id},
            json={
                "expected_revision_id": answered_body["state"]["authoritative_revision_id"],
                "message_id": correction_message["message_id"],
            },
        )
        assert correction.status_code == 200, correction.json()
        assert correction.json()["state"]["enrichment_cycle_number"] == 3
        assert correction.json()["state"]["clarification_plan_id"]

        final_output = client.get(
            f"/v1/sessions/{session_id}/prompt-enrichment/final-output",
            headers={"X-Organization-ID": organization_id},
        )
        assert final_output.status_code in {200, 409}
        if final_output.status_code == 409:
            assert final_output.json()["error"] == "final_output_not_ready"
        assert text_provider.calls == []


def test_controlled_http_routes_enforce_authentication_and_organization_scope(engine, tmp_path):
    internal_service = build_service(engine)
    runtime, *_ = _runtime(internal_service, tmp_path)
    client, _ = _client(engine, runtime)
    with client:
        organization_id, _, session_response = create_hierarchy(client)
        session_id = session_response.json()["session_id"]
        foreign_id = client.post("/organizations", json={"name": "Foreign"}).json()[
            "organization_id"
        ]

        unauthenticated = client.get(
            f"/v1/sessions/{session_id}/prompt-enrichment/state",
            headers={"Authorization": "", "X-Organization-ID": organization_id},
        )
        assert unauthenticated.status_code == 401
        cross_scope = client.get(
            f"/v1/sessions/{session_id}/prompt-enrichment/state",
            headers={"X-Organization-ID": foreign_id},
        )
        assert cross_scope.status_code == 404
        assert cross_scope.json()["error"] == "not_found"
