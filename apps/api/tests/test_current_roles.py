"""ROLES-001 current-catalog integration; no historical-role compatibility."""

from uuid import UUID

import pytest
from conftest import create_hierarchy
from jewelai_domain.roles import UnknownRoleError
from jewelai_persistence import create_session_factory
from jewelai_persistence.models import RoleRow
from jewelai_persistence.roles import database_role_registry, import_roles


def test_current_import_and_cache_refresh(engine):
    factory = create_session_factory(engine)
    assert import_roles(factory) == {"inserted": 0, "updated": 0, "unchanged": 21}
    registry = database_role_registry(factory)
    assert len(registry) == 21
    profiles = [registry.get_profile(r) for r in registry]
    assert sum("passport" in p.role_data for p in profiles) == 9
    assert sum(len(p.role_data["personas"]) for p in profiles) == 36
    before = registry.get_profile("RR-C25")
    with factory.begin() as db:
        r = db.get(RoleRow, "RR-C25")
        r.name_ru += " [test]"
        r.revision += 1
    assert registry.get_profile("RR-C25").revision == before.revision + 1
    assert registry.get_profile("RR-C25").name_ru.endswith("[test]")
    for old in [
        "retail_client",
        "sales_manager",
        "buyer",
        "marketing",
        "jewelry_designer",
        "industrial_designer",
        "RR-C01",
        "RR-C99",
    ]:
        with pytest.raises(UnknownRoleError):
            registry.get_profile(old)


def test_http_current_catalog_and_selection(client):
    catalog = client.get("/ui/catalog")
    assert catalog.status_code == 200, catalog.text
    assert len(catalog.json()["roles"]) == 9
    assert len(client.get("/roles").json()) == 21
    contexts = []
    for role in ["RR-C25", "RR-C10"]:
        org, project, response = create_hierarchy(client, role_id=role)
        assert response.status_code == 201, response.text
        assert response.json()["role_id"] == role
        context = client.get(f"/roles/{role}/context").json()
        contexts.append(context)
        assert context["conversation_policy"] is None
        assert context["passport"]["maturity"] == "DRAFT_NOT_OWNER_APPROVED"
        assert context["authorization_effect"] == "none"
    assert contexts[0]["registry"] != contexts[1]["registry"]
    for role in [
        "retail_client",
        "sales_manager",
        "buyer",
        "marketing",
        "jewelry_designer",
        "industrial_designer",
        "RR-C02",
        "RR-C01",
    ]:
        _, _, response = create_hierarchy(client, role_id=role)
        assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("role", "locale", "text"),
    [
        ("RR-C25", "en", "I want a ring with an emerald."),
        ("RR-C10", "ru", "Хочу кольцо с изумрудом."),
    ],
)
def test_role_http_journey_restart_and_cas(
    client, app, engine, text_understanding_provider, role, locale, text
):
    from jewelai_parser import ParserCandidate

    org, _, response = create_hierarchy(client, role_id=role, locale=locale)
    session = response.json()
    url = f"/sessions/{session['session_id']}"
    headers = {"X-Organization-ID": org}
    text_understanding_provider.candidate = ParserCandidate.model_validate(
        {
            "updates": [
                {
                    "target": "jewelry_type",
                    "value": {"kind": "term", "text": "ring" if locale == "en" else "кольцо"},
                },
                {
                    "target": "center_stone.material",
                    "value": {"kind": "term", "text": "emerald" if locale == "en" else "изумруд"},
                },
            ]
        }
    )
    first = client.post(
        url + "/text-intake",
        headers=headers,
        json={"content": text, "expected_revision_id": session["current_revision_id"]},
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["revision"]["design"]["center_stone"]["material"]["value"] == "emerald"
    assert body["evaluation"]["decision"]["question_id"] == "CENTER_STONE_SHAPE"
    assert body["evaluation"]["rendered_question"]["locale"] == locale
    text_understanding_provider.candidate = ParserCandidate.model_validate(
        {
            "updates": [
                {
                    "target": "center_stone.shape",
                    "value": {"kind": "term", "text": "oval" if locale == "en" else "овал"},
                },
            ]
        }
    )
    request = {
        "content": "Oval" if locale == "en" else "Овальный",
        "expected_revision_id": body["revision"]["revision_id"],
    }
    second = client.post(url + "/text-intake", headers=headers, json=request)
    assert second.status_code == 201, second.text
    revision = second.json()["revision"]
    assert revision["design"]["center_stone"]["shape"]["value"] == "oval"
    assert revision["design"]["center_stone"]["dimensions"] is None
    stale = client.post(url + "/text-intake", headers=headers, json=request)
    assert stale.status_code == 409, stale.text
    assert client.get(url, headers=headers).json()["current_revision_id"] == revision["revision_id"]
    # Fresh repository/registry instance reads the same durable role and state.
    from jewelai_persistence.repository import PersistenceRepository

    factory = create_session_factory(engine)
    assert database_role_registry(factory).get_profile(role).revision == 1
    restored = PersistenceRepository(factory).get_design_session(
        UUID(session["session_id"]), UUID(org)
    )
    assert str(restored.current_revision_id) == revision["revision_id"]
    from test_prompt_enrichment_http import _client

    with _client(engine)[0] as restarted:
        restored_http = restarted.get(url, headers=headers)
        assert restored_http.status_code == 200
        assert restored_http.json()["current_revision_id"] == revision["revision_id"]
        persisted = restarted.get(url + "/revisions/" + revision["revision_id"], headers=headers)
        assert persisted.status_code == 200
        assert persisted.json()["design"] == revision["design"]
        assert restarted.get("/roles/" + role).json()["revision"] == 1
        forbidden = restarted.get(url, headers={**headers, "Authorization": "Bearer test-outsider"})
        assert forbidden.status_code in (403, 404)


def test_seed_sources_and_transactional_import(engine):
    import hashlib
    import json
    from copy import deepcopy

    from conftest import ROOT

    seed = json.loads(
        (ROOT / "packages/persistence/src/jewelai_persistence/role_seed.json").read_text()
    )
    from zipfile import ZipFile

    sources = ZipFile(ROOT / "data/roles/sources/original-role-sources.zip")
    for record in seed:
        for kind in ("registry", "passport"):
            source = record["role_data"].get(kind)
            if source is not None:
                raw = sources.read(source["source_id"])
                assert raw.decode() == source["content"]
                assert hashlib.sha256(raw).hexdigest() == source["sha256"]
        cards = sources.read("COMPACT_PERSONA_CARDS_36_v0.5_RU.md").decode()
        for persona in record["role_data"]["personas"]:
            assert persona["content"] in cards
    factory = create_session_factory(engine)
    changed = deepcopy(seed)
    changed[0]["name_ru"] += " [synthetic update]"
    assert import_roles(factory, changed) == {"inserted": 0, "updated": 1, "unchanged": 20}
    assert database_role_registry(factory)[changed[0]["role_id"]].revision == 2
    assert import_roles(factory, changed) == {"inserted": 0, "updated": 0, "unchanged": 21}
    changed[1]["role_data"]["registry"]["content"] += "tampered"
    with pytest.raises(ValueError, match="source integrity"):
        import_roles(factory, changed)
    assert database_role_registry(factory)[changed[0]["role_id"]].revision == 2


def test_malformed_role_fails_closed_without_state_change(client, engine):
    org, _, response = create_hierarchy(client)
    session = response.json()
    factory = create_session_factory(engine)
    with factory.begin() as db:
        role = db.get(RoleRow, "RR-C25")
        role.role_data = {
            "authorization_effect": "owner",
            "provider_secret": "synthetic-redaction-marker",
        }
    failed = client.get("/roles/RR-C25")
    assert failed.status_code == 503
    assert failed.json()["error"] == "role_catalog_unavailable"
    assert "synthetic-redaction-marker" not in failed.text
    current = client.get(f"/sessions/{session['session_id']}", headers={"X-Organization-ID": org})
    assert current.status_code == 200
    assert current.json()["current_revision_id"] == session["current_revision_id"]


def test_runtime_never_reads_role_seed_or_legacy_json(engine, monkeypatch):
    from pathlib import Path

    from test_prompt_enrichment_http import _client

    original = Path.read_text

    def guarded(path, *args, **kwargs):
        if path.name == "role_seed.json" or "/data/roles/" in str(path):
            raise AssertionError("Runtime attempted a role-file fallback")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    with _client(engine)[0] as client:
        assert len(client.get("/roles").json()) == 21
        role = client.get("/roles/RR-C25")
        assert role.status_code == 200
        assert role.json()["created_at"] is not None
        assert len(client.get("/ui/catalog").json()["roles"]) == 9
