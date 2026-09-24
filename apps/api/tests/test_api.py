import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from conftest import NOW, create_hierarchy
from jewelai_assets import Asset, AssetContentType, AssetKind, AssetStatus, build_object_key
from jewelai_domain import Design
from jewelai_generation import GatewayRegistry, execute_generation_run
from jewelai_model_gateway import GeneratedOutputDescriptor, GenerationResult

from jewelai_api.artifacts import ArtifactConfigurationError, load_runtime_artifacts
from jewelai_api.schemas import EditRevisionRequest
from jewelai_api.settings import ArtifactVersions

ROOT = Path(__file__).resolve().parents[3]


def source(message_id):
    return {
        "kind": "message",
        "message_id": message_id,
        "recorded_at": NOW.isoformat(),
    }


def explicit(message_id, value):
    return {
        "availability": "value",
        "origin": "explicit",
        "value": value,
        "source": source(message_id),
        "confirmed": False,
        "locked": False,
    }


def transition(action, expected, *, target=None, design=None, message_id="transition"):
    payload = {
        "action": action,
        "expected_revision_id": expected,
        "source": source(message_id),
        "reason": f"Test {action}",
    }
    if target is not None:
        payload["target"] = target
    if design is not None:
        payload["proposed_design"] = design
    return payload


def test_health_organization_project_session_and_scope(client):
    assert client.get("/health").json() == {"status": "ok"}
    organization_id, project_id, session = create_hierarchy(client, locale="ru-RU")
    assert session.status_code == 201
    body = session.json()
    assert body["project_id"] == project_id
    assert body["role_id"] == "retail_client"
    assert body["locale"] == "ru"
    assert set(body["artifacts"].values()) == {"1.0.0"}

    response = client.get(
        f"/sessions/{body['session_id']}",
        headers={"X-Organization-ID": organization_id},
    )
    assert response.status_code == 200
    assert response.json() == body
    foreign = client.post("/organizations", json={"name": "Organization B"}).json()
    response = client.get(
        f"/sessions/{body['session_id']}",
        headers={"X-Organization-ID": foreign["organization_id"]},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
    response = client.post(
        f"/sessions/{body['session_id']}/revisions",
        headers={"X-Organization-ID": foreign["organization_id"]},
        json=transition(
            "edit", body["current_revision_id"], design=Design().model_dump(mode="json")
        ),
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("role_id", "locale", "error"),
    [
        ("administrator", "en", "invalid_role"),
        ("retail_client", "de", "unsupported_locale"),
    ],
)
def test_session_rejects_invalid_role_and_locale(client, role_id, locale, error):
    organization = client.post("/organizations", json={"name": "Organization"}).json()
    organization_id = organization["organization_id"]
    project = client.post(
        f"/organizations/{organization_id}/projects", json={"name": "Project"}
    ).json()
    response = client.post(
        f"/projects/{project['project_id']}/sessions",
        headers={"X-Organization-ID": organization_id},
        json={"role_id": role_id, "locale": locale},
    )
    assert response.status_code == 422
    assert response.json()["error"] == error


def test_revision_transition_history_locking_and_stale_conflict(client):
    organization_id, _, session_response = create_hierarchy(client)
    session = session_response.json()
    headers = {"X-Organization-ID": organization_id}
    revisions_url = f"/sessions/{session['session_id']}/revisions"
    initial = client.get(revisions_url, headers=headers).json()["revisions"][0]
    original_snapshot = deepcopy(initial)

    design = initial["design"]
    design["center_stone"]["shape"] = explicit("shape-oval", "oval")
    edited = client.post(
        revisions_url,
        headers=headers,
        json=transition("edit", initial["revision_id"], design=design),
    )
    assert edited.status_code == 200
    edited = edited.json()

    stale = client.post(
        revisions_url,
        headers=headers,
        json=transition("edit", initial["revision_id"], design=Design().model_dump(mode="json")),
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "stale_revision"

    confirmed = client.post(
        revisions_url,
        headers=headers,
        json=transition("confirm", edited["revision_id"], target="center_stone.shape"),
    ).json()
    locked = client.post(
        revisions_url,
        headers=headers,
        json=transition("lock", confirmed["revision_id"], target="center_stone.shape"),
    ).json()

    changed = locked["design"]
    changed["center_stone"]["shape"] = explicit("shape-round", "round")
    blocked = client.post(
        revisions_url,
        headers=headers,
        json=transition("edit", locked["revision_id"], design=changed),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "locked_field_conflict"

    unlocked = client.post(
        revisions_url,
        headers=headers,
        json=transition("unlock", locked["revision_id"], target="center_stone.shape"),
    ).json()
    changed = unlocked["design"]
    changed["center_stone"]["shape"] = explicit("shape-round", "round")
    changed = client.post(
        revisions_url,
        headers=headers,
        json=transition("edit", unlocked["revision_id"], design=changed),
    ).json()
    reconfirmed = client.post(
        revisions_url,
        headers=headers,
        json=transition("confirm", changed["revision_id"], target="center_stone.shape"),
    ).json()
    assert reconfirmed["design"]["center_stone"]["shape"]["confirmed"]

    history = client.get(revisions_url, headers=headers).json()["revisions"]
    assert len(history) == 7
    assert history[0] == original_snapshot
    assert [item["revision"] for item in history] == list(range(1, 8))
    fetched = client.get(f"{revisions_url}/{history[3]['revision_id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == history[3]


def test_runtime_evaluation_renders_ask_persists_event_and_does_not_mutate(client, app):
    organization_id, _, session_response = create_hierarchy(client)
    session = session_response.json()
    headers = {"X-Organization-ID": organization_id}
    revisions_url = f"/sessions/{session['session_id']}/revisions"
    initial = client.get(revisions_url, headers=headers).json()["revisions"][0]
    design = initial["design"]
    design["jewelry_type"] = explicit("jewelry-type", "ring")
    design["center_stone"]["material"] = explicit("material", "emerald")
    design["center_stone"]["weight"] = explicit("weight", {"value": 3.0, "unit": "ct"})
    edited = client.post(
        revisions_url,
        headers=headers,
        json=transition("edit", initial["revision_id"], design=design),
    ).json()

    first = client.post(f"/sessions/{session['session_id']}/evaluate", headers=headers, json={})
    second = client.post(f"/sessions/{session['session_id']}/evaluate", headers=headers, json={})
    assert first.status_code == second.status_code == 200
    assert first.json()["decision"] == second.json()["decision"]
    result = first.json()
    assert result["revision_id"] == edited["revision_id"]
    assert result["decision"]["decision"] == "ask"
    assert result["decision"]["question_id"] == "CENTER_STONE_SHAPE"
    assert result["rendered_question"]["role_id"] == "retail_client"
    assert result["rendered_question"]["locale"] == "en"

    after = client.get(f"/sessions/{session['session_id']}", headers=headers).json()
    assert after["current_revision_id"] == edited["revision_id"]
    persisted = client.get(f"{revisions_url}/{edited['revision_id']}", headers=headers).json()
    assert persisted["design"]["center_stone"]["dimensions"] is None
    events = app.state.service.repository.list_question_events(
        UUID(session["session_id"]), UUID(organization_id)
    )
    assert len(events) == 2
    assert {event.semantic_question_id for event in events} == {"CENTER_STONE_SHAPE"}
    assert all(event.specification_revision_id == UUID(edited["revision_id"]) for event in events)
    assert all("trace" in event.trace_payload for event in events)


def test_derive_decision_returns_proposal_without_applying_it(client):
    organization_id, _, session_response = create_hierarchy(client)
    session = session_response.json()
    headers = {"X-Organization-ID": organization_id}
    revisions_url = f"/sessions/{session['session_id']}/revisions"
    initial = client.get(revisions_url, headers=headers).json()["revisions"][0]
    design = initial["design"]
    design["jewelry_type"] = explicit("jewelry-type", "ring")
    design["center_stone"]["material"] = explicit("material", "emerald")
    design["center_stone"]["weight"] = explicit("weight", {"value": 3.0, "unit": "ct"})
    design["center_stone"]["shape"] = explicit("shape", "oval")
    design["center_stone"]["setting"] = explicit("setting", "prong_setting")
    design["metal"]["color"] = explicit("metal-color", "white")
    edited = client.post(
        revisions_url,
        headers=headers,
        json=transition("edit", initial["revision_id"], design=design),
    ).json()
    fact = {
        "target": "center_stone.dimensions",
        "value": {
            "length": {"value": 9.1, "unit": "mm"},
            "width": {"value": 7.2, "unit": "mm"},
            "depth": {"value": 4.8, "unit": "mm"},
        },
        "source": {
            "kind": "knowledge",
            "record_id": "test-sourced-estimate",
            "version": "1.0.0",
            "recorded_at": NOW.isoformat(),
        },
        "uncertainty": "Synthetic integration-test estimate, not a production gemstone fact.",
        "match": {
            "jewelry_type": "ring",
            "center_stone_material": "emerald",
            "center_stone_weight": {"value": 3.0, "unit": "ct"},
        },
    }
    response = client.post(
        f"/sessions/{session['session_id']}/evaluate",
        headers=headers,
        json={"knowledge_facts": [fact]},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["decision"]["decision"] == "derive"
    assert result["decision"]["proposed_change"]["kind"] == "derived"
    after = client.get(f"{revisions_url}/{edited['revision_id']}", headers=headers).json()
    assert after["design"]["center_stone"]["dimensions"] is None
    current = client.get(f"/sessions/{session['session_id']}", headers=headers).json()
    assert current["current_revision_id"] == edited["revision_id"]


def test_message_parser_proposal_apply_and_evaluate_flow(client, app):
    organization_id, _, session_response = create_hierarchy(client)
    session = session_response.json()
    headers = {"X-Organization-ID": organization_id}
    session_url = f"/sessions/{session['session_id']}"
    message = client.post(
        f"{session_url}/messages",
        headers=headers,
        json={"content": "I want a ring with a 3 ct emerald."},
    )
    assert message.status_code == 201
    assert message.json()["actor"] == "user"

    candidate = {
        "schema_version": "1.0.0",
        "updates": [
            {"target": "jewelry_type", "value": {"kind": "term", "text": "ring"}},
            {
                "target": "center_stone.material",
                "value": {"kind": "term", "text": "emerald"},
            },
            {
                "target": "center_stone.weight",
                "value": {"kind": "weight", "value": {"value": 3.0, "unit": "ct"}},
            },
        ],
    }
    proposal_response = client.post(
        f"{session_url}/parser-proposals",
        headers=headers,
        json={
            "expected_revision_id": session["current_revision_id"],
            "message_id": message.json()["message_id"],
            "candidate": candidate,
        },
    )
    assert proposal_response.status_code == 200
    proposal_body = proposal_response.json()
    assert proposal_body["has_changes"]
    assert proposal_body["issues"] == []
    assert proposal_body["proposed_design"]["center_stone"]["dimensions"] is None
    canonical = {
        item["concrete_target"]: item["canonical_value"]
        for item in proposal_body["accepted_updates"]
    }
    assert canonical == {
        "center_stone.material": "emerald",
        "center_stone.weight": {"value": 3.0, "unit": "ct"},
        "jewelry_type": "ring",
    }

    unchanged = client.get(session_url, headers=headers).json()
    assert unchanged["current_revision_id"] == session["current_revision_id"]
    applied = client.post(
        f"{session_url}/revisions",
        headers=headers,
        json=transition(
            "edit",
            proposal_body["expected_revision_id"],
            design=proposal_body["proposed_design"],
            message_id=proposal_body["source"]["message_id"],
        ),
    )
    assert applied.status_code == 200
    applied_material = applied.json()["design"]["center_stone"]["material"]
    assert applied_material["origin"] == "explicit"
    assert applied_material["source"]["message_id"] == message.json()["message_id"]
    assert not applied_material["confirmed"]
    assert not applied_material["locked"]

    evaluated = client.post(f"{session_url}/evaluate", headers=headers, json={})
    assert evaluated.status_code == 200
    assert evaluated.json()["decision"]["question_id"] == "CENTER_STONE_SHAPE"
    assert evaluated.json()["rendered_question"]["locale"] == "en"
    assert (
        client.get(
            f"{session_url}/revisions/{applied.json()['revision_id']}", headers=headers
        ).json()["design"]["center_stone"]["dimensions"]
        is None
    )
    stored = app.state.service.repository.get_message(
        UUID(session["session_id"]), UUID(message.json()["message_id"]), UUID(organization_id)
    )
    assert stored.content == "I want a ring with a 3 ct emerald."


def test_parser_proposal_scope_cross_session_message_and_staleness(client):
    organization_id, _, first_response = create_hierarchy(client)
    first = first_response.json()
    headers = {"X-Organization-ID": organization_id}
    first_url = f"/sessions/{first['session_id']}"
    first_message = client.post(
        f"{first_url}/messages", headers=headers, json={"content": "Oval center stone"}
    ).json()

    foreign = client.post("/organizations", json={"name": "Foreign"}).json()
    denied = client.post(
        f"{first_url}/messages",
        headers={"X-Organization-ID": foreign["organization_id"]},
        json={"content": "Should not be stored"},
    )
    assert denied.status_code == 404

    foreign_project = client.post(
        f"/organizations/{foreign['organization_id']}/projects",
        json={"name": "Foreign project"},
    ).json()
    foreign_session = client.post(
        f"/projects/{foreign_project['project_id']}/sessions",
        headers={"X-Organization-ID": foreign["organization_id"]},
        json={"role_id": "retail_client", "locale": "en"},
    ).json()
    foreign_message = client.post(
        f"/sessions/{foreign_session['session_id']}/messages",
        headers={"X-Organization-ID": foreign["organization_id"]},
        json={"content": "Foreign message"},
    ).json()
    foreign_provenance = client.post(
        f"{first_url}/parser-proposals",
        headers=headers,
        json={
            "expected_revision_id": first["current_revision_id"],
            "message_id": foreign_message["message_id"],
            "candidate": {"schema_version": "1.0.0", "updates": []},
        },
    )
    assert foreign_provenance.status_code == 404

    project = client.post(
        f"/organizations/{organization_id}/projects", json={"name": "Second project"}
    ).json()
    second = client.post(
        f"/projects/{project['project_id']}/sessions",
        headers=headers,
        json={"role_id": "industrial_designer", "locale": "en"},
    ).json()
    wrong_message = client.post(
        f"/sessions/{second['session_id']}/parser-proposals",
        headers=headers,
        json={
            "expected_revision_id": second["current_revision_id"],
            "message_id": first_message["message_id"],
            "candidate": {"schema_version": "1.0.0", "updates": []},
        },
    )
    assert wrong_message.status_code == 404

    request = {
        "expected_revision_id": first["current_revision_id"],
        "message_id": first_message["message_id"],
        "candidate": {
            "schema_version": "1.0.0",
            "updates": [
                {
                    "target": "center_stone.shape",
                    "value": {"kind": "term", "text": "oval"},
                }
            ],
        },
    }
    old_proposal = client.post(f"{first_url}/parser-proposals", headers=headers, json=request)
    assert old_proposal.status_code == 200
    applied = client.post(
        f"{first_url}/revisions",
        headers=headers,
        json=transition(
            "edit",
            first["current_revision_id"],
            design=old_proposal.json()["proposed_design"],
        ),
    )
    assert applied.status_code == 200
    stale_proposal = client.post(f"{first_url}/parser-proposals", headers=headers, json=request)
    assert stale_proposal.status_code == 409
    stale_apply = client.post(
        f"{first_url}/revisions",
        headers=headers,
        json=transition(
            "edit",
            first["current_revision_id"],
            design=old_proposal.json()["proposed_design"],
        ),
    )
    assert stale_apply.status_code == 409


def test_artifact_loader_requires_explicit_existing_version():
    with pytest.raises(ArtifactConfigurationError, match="missing"):
        load_runtime_artifacts(ROOT, ArtifactVersions(rules="9.9.9"))
    with pytest.raises(ArtifactConfigurationError, match="missing"):
        load_runtime_artifacts(ROOT, ArtifactVersions(prompts="9.9.9"))


def ready_design():
    fixture = json.loads(
        (ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json").read_text()
    )["design"]

    def unconfirm(value):
        if isinstance(value, dict):
            if value.get("availability") == "value":
                value["confirmed"] = False
                value["locked"] = False
            for child in value.values():
                unconfirm(child)
        elif isinstance(value, list):
            for child in value:
                unconfirm(child)

    unconfirm(fixture)
    fixture["center_stone"]["dimensions"] = explicit(
        "ready-dimensions",
        {
            "length": {"value": 9.1, "unit": "mm"},
            "width": {"value": 7.2, "unit": "mm"},
            "depth": {"value": 4.8, "unit": "mm"},
        },
    )
    fixture["center_stone"]["setting"] = explicit("ready-setting", "prong_setting")
    return fixture


def test_prompt_compile_requires_ready_without_question_side_effect(client, app):
    organization_id, _, response = create_hierarchy(client)
    session = response.json()
    headers = {"X-Organization-ID": organization_id}
    url = f"/sessions/{session['session_id']}/prompt-revisions"
    result = client.post(
        url,
        headers=headers,
        json={"expected_revision_id": session["current_revision_id"]},
    )
    assert result.status_code == 409
    assert result.json()["error"] == "specification_not_ready"
    assert client.get(url, headers=headers).json() == {"prompt_revisions": []}
    assert (
        app.state.service.repository.list_question_events(
            UUID(session["session_id"]), UUID(organization_id)
        )
        == ()
    )
    assert (
        client.get(f"/sessions/{session['session_id']}", headers=headers).json()[
            "current_revision_id"
        ]
        == session["current_revision_id"]
    )


def test_ready_prompt_compile_get_list_scope_and_request_strictness(client, app):
    organization_id, _, response = create_hierarchy(client, role_id="industrial_designer")
    session = response.json()
    headers = {"X-Organization-ID": organization_id}
    revisions_url = f"/sessions/{session['session_id']}/revisions"
    edited = client.post(
        revisions_url,
        headers=headers,
        json=transition(
            "edit",
            session["current_revision_id"],
            design=ready_design(),
            message_id="ready-design",
        ),
    )
    assert edited.status_code == 200
    edited = edited.json()
    confirmed = client.post(
        revisions_url,
        headers=headers,
        json=transition("confirm", edited["revision_id"], target="metal.color"),
    ).json()
    locked = client.post(
        revisions_url,
        headers=headers,
        json=transition("lock", confirmed["revision_id"], target="metal.color"),
    )
    assert locked.status_code == 200
    locked = locked.json()
    prompt_url = f"/sessions/{session['session_id']}/prompt-revisions"
    created = client.post(
        prompt_url,
        headers=headers,
        json={"expected_revision_id": locked["revision_id"]},
    )
    assert created.status_code == 201
    body = created.json()
    compiled = body["compiled_prompt"]
    assert body["specification_revision_id"] == locked["revision_id"]
    assert compiled["template_artifact_version"] == "1.0.0"
    locks = {item["concrete_target"]: item for item in compiled["locked_constraints"]}
    assert locks["metal.color"]["value"] == "white"
    assert "LOCKED CONSTRAINTS — MUST NOT CHANGE" in compiled["prompt_text"]
    assert "metal.color" in compiled["prompt_text"]

    listed = client.get(prompt_url, headers=headers).json()["prompt_revisions"]
    assert listed == [body]
    fetched = client.get(f"{prompt_url}/{body['prompt_revision_id']}", headers=headers)
    assert fetched.status_code == 200 and fetched.json() == body

    current = client.get(f"/sessions/{session['session_id']}", headers=headers).json()
    assert current["current_revision_id"] == locked["revision_id"]
    assert current["artifacts"]["prompts"] == "1.0.0"
    assert (
        app.state.service.repository.list_question_events(
            UUID(session["session_id"]), UUID(organization_id)
        )
        == ()
    )

    bad = client.post(
        prompt_url,
        headers=headers,
        json={
            "expected_revision_id": locked["revision_id"],
            "prompt_text": "caller-controlled",
            "provider": "forbidden",
        },
    )
    assert bad.status_code == 422
    stale = client.post(
        prompt_url,
        headers=headers,
        json={"expected_revision_id": session["current_revision_id"]},
    )
    assert stale.status_code == 409

    foreign = client.post("/organizations", json={"name": "Foreign prompt reader"}).json()
    denied = client.get(
        f"{prompt_url}/{body['prompt_revision_id']}",
        headers={"X-Organization-ID": foreign["organization_id"]},
    )
    assert denied.status_code == 404


def test_prompt_compile_rechecks_current_revision_before_persistence(client, app):
    organization_id, _, response = create_hierarchy(client)
    session = response.json()
    headers = {"X-Organization-ID": organization_id}
    revisions_url = f"/sessions/{session['session_id']}/revisions"
    edited = client.post(
        revisions_url,
        headers=headers,
        json=transition(
            "edit",
            session["current_revision_id"],
            design=ready_design(),
            message_id="ready-for-race",
        ),
    ).json()

    def advance_revision():
        design = deepcopy(edited["design"])
        design["center_stone"]["cut"] = explicit("concurrent-cut", "step_cut")
        app.state.service.transition_revision(
            UUID(session["session_id"]),
            UUID(organization_id),
            EditRevisionRequest.model_validate(
                transition(
                    "edit",
                    edited["revision_id"],
                    design=design,
                    message_id="concurrent-write",
                )
            ),
        )

    app.state.service._before_prompt_persist = advance_revision
    prompt_url = f"/sessions/{session['session_id']}/prompt-revisions"
    result = client.post(
        prompt_url,
        headers=headers,
        json={"expected_revision_id": edited["revision_id"]},
    )
    app.state.service._before_prompt_persist = None
    assert result.status_code == 409
    assert result.json()["error"] == "stale_revision"
    assert client.get(prompt_url, headers=headers).json() == {"prompt_revisions": []}


class ApiTestGateway:
    def __init__(self):
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return GenerationResult(
            generation_run_id=request.generation_run_id,
            provider=request.provider,
            model=request.model,
            provider_request_id="api-test-request",
            outputs=(GeneratedOutputDescriptor(ordinal=1, provider_output_id="api-test-output"),),
        )


def create_ready_prompt(client):
    organization_id, project_id, response = create_hierarchy(client)
    session = response.json()
    headers = {"X-Organization-ID": organization_id}
    edited = client.post(
        f"/sessions/{session['session_id']}/revisions",
        headers=headers,
        json=transition(
            "edit",
            session["current_revision_id"],
            design=ready_design(),
            message_id="generation-ready",
        ),
    ).json()
    prompt = client.post(
        f"/sessions/{session['session_id']}/prompt-revisions",
        headers=headers,
        json={"expected_revision_id": edited["revision_id"]},
    )
    assert prompt.status_code == 201
    return organization_id, project_id, session, edited, prompt.json()


def test_generation_run_api_creates_pending_without_inline_provider_and_reads_terminal(client, app):
    organization_id, _, session, edited, prompt = create_ready_prompt(client)
    headers = {"X-Organization-ID": organization_id}
    url = f"/sessions/{session['session_id']}/generation-runs"
    gateway = ApiTestGateway()
    created = client.post(
        url,
        headers=headers,
        json={"prompt_revision_id": prompt["prompt_revision_id"], "profile_id": "test_default"},
    )
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "pending"
    assert run["profile_id"] == "test_default"
    assert run["profile_version"] == "1.0.0"
    assert run["provider"] == "test"
    assert run["model"] == "deterministic-image-v1"
    assert run["configuration"] == {"output_count": 1}
    assert run["prompt_content_hash"] == prompt["compiled_prompt"]["content_hash"]
    assert gateway.calls == 0
    assert client.get(url, headers=headers).json() == {"generation_runs": [run]}
    assert client.get(f"{url}/{run['generation_run_id']}", headers=headers).json() == run
    assert (
        client.get(f"/sessions/{session['session_id']}", headers=headers).json()[
            "current_revision_id"
        ]
        == edited["revision_id"]
    )

    outcome = execute_generation_run(
        app.state.service.repository,
        session_id=UUID(session["session_id"]),
        generation_run_id=UUID(run["generation_run_id"]),
        organization_id=UUID(organization_id),
        gateways=GatewayRegistry({"test": gateway}),
        clock=iter((NOW + timedelta(seconds=1), NOW + timedelta(seconds=2))).__next__,
    )
    assert outcome.disposition == "succeeded"
    assert gateway.calls == 1
    terminal = client.get(f"{url}/{run['generation_run_id']}", headers=headers).json()
    assert terminal["status"] == "succeeded"
    assert terminal["result"]["provider_request_id"] == "api-test-request"
    assert terminal["result"]["outputs"][0]["provider_output_id"] == "api-test-output"


def test_generation_run_api_rejects_untrusted_profile_configuration_and_cross_scope(client):
    organization_id, _, session, edited, prompt = create_ready_prompt(client)
    headers = {"X-Organization-ID": organization_id}
    url = f"/sessions/{session['session_id']}/generation-runs"
    unknown = client.post(
        url,
        headers=headers,
        json={"prompt_revision_id": prompt["prompt_revision_id"], "profile_id": "unknown"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"] == "unknown_generation_profile"
    arbitrary = client.post(
        url,
        headers=headers,
        json={
            "prompt_revision_id": prompt["prompt_revision_id"],
            "profile_id": "test_default",
            "provider": "caller-provider",
            "configuration": {"output_count": 4},
        },
    )
    assert arbitrary.status_code == 422

    second_project = client.post(
        f"/organizations/{organization_id}/projects", json={"name": "Second project"}
    ).json()
    second_session = client.post(
        f"/projects/{second_project['project_id']}/sessions",
        headers=headers,
        json={"role_id": "retail_client", "locale": "en"},
    ).json()
    wrong_session = client.post(
        f"/sessions/{second_session['session_id']}/generation-runs",
        headers=headers,
        json={"prompt_revision_id": prompt["prompt_revision_id"], "profile_id": "test_default"},
    )
    assert wrong_session.status_code == 404

    created = client.post(
        url,
        headers=headers,
        json={"prompt_revision_id": prompt["prompt_revision_id"], "profile_id": "test_default"},
    ).json()
    foreign = client.post("/organizations", json={"name": "Foreign generation reader"}).json()
    denied = client.get(
        f"{url}/{created['generation_run_id']}",
        headers={"X-Organization-ID": foreign["organization_id"]},
    )
    assert denied.status_code == 404

    newer_design = deepcopy(edited["design"])
    newer_design["center_stone"]["cut"] = explicit("later-cut", "step_cut")
    newer = client.post(
        f"/sessions/{session['session_id']}/revisions",
        headers=headers,
        json=transition(
            "edit",
            edited["revision_id"],
            design=newer_design,
            message_id="later-design-revision",
        ),
    )
    assert newer.status_code == 200
    historical = client.get(f"{url}/{created['generation_run_id']}", headers=headers)
    assert historical.status_code == 200
    assert historical.json()["prompt_revision_id"] == prompt["prompt_revision_id"]
    assert historical.json()["status"] == "pending"


def test_asset_metadata_api_is_scoped_ordered_and_redacts_storage_details(client, app):
    organization_id, project_id, response = create_hierarchy(client)
    session = response.json()
    headers = {"X-Organization-ID": organization_id}
    asset_ids = (
        UUID("40404040-4040-4040-8040-404040404040"),
        UUID("41414141-4141-4141-8141-414141414141"),
    )
    for offset, asset_id in enumerate(asset_ids):
        asset = Asset(
            asset_id=asset_id,
            organization_id=UUID(organization_id),
            project_id=UUID(project_id),
            session_id=UUID(session["session_id"]),
            kind=AssetKind.REFERENCE,
            status=AssetStatus.PENDING,
            object_key=build_object_key(
                UUID(organization_id),
                UUID(project_id),
                asset_id,
                AssetContentType.PNG,
            ),
            content_type=AssetContentType.PNG,
            content_hash=str(offset) * 64,
            byte_size=16 + offset,
            created_at=NOW + timedelta(seconds=offset),
        )
        app.state.service.repository.create_pending_asset(asset)
        app.state.service.repository.mark_asset_ready(
            asset_id,
            UUID(organization_id),
            NOW + timedelta(seconds=offset + 2),
        )

    url = f"/sessions/{session['session_id']}/assets"
    listed = client.get(url, headers=headers)
    assert listed.status_code == 200
    payload = listed.json()
    assert [item["asset_id"] for item in payload["assets"]] == [str(item) for item in asset_ids]
    single = client.get(f"{url}/{asset_ids[0]}", headers=headers)
    assert single.status_code == 200
    assert single.json() == payload["assets"][0]
    forbidden_fields = {"object_key", "bucket", "url", "bytes", "provider_output_id"}
    assert forbidden_fields.isdisjoint(single.json())

    foreign = client.post("/organizations", json={"name": "Foreign asset reader"}).json()
    denied = client.get(
        f"{url}/{asset_ids[0]}",
        headers={"X-Organization-ID": foreign["organization_id"]},
    )
    assert denied.status_code == 404
