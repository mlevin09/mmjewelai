from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from conftest import NOW, create_hierarchy
from jewelai_domain import Design

from jewelai_api.artifacts import ArtifactConfigurationError, load_runtime_artifacts
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
