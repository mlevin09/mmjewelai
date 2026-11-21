"""Read-only Knowledge HTTP endpoints over the real app (ADR 0048), behind the PostgreSQL gate."""

import pytest
from conftest import (
    ROOT,
    FakeAssetAccessSigner,
    FakeGenerationTaskPublisher,
    FakePrivateObjectStore,
    FakeTextUnderstandingProvider,
    FakeTokenVerifier,
)
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_knowledge_kb_postgres import PILOT, pilot  # noqa: F401  (module-scoped fixture)

from jewelai_api import create_app
from jewelai_api.knowledge_routes import KnowledgeHttpConfig
from jewelai_api.settings import RuntimeSettings

pytestmark = pytest.mark.postgres


def _client(engine, knowledge_http):
    app = create_app(
        RuntimeSettings(
            database_url="postgresql+psycopg://unused",
            repository_root=ROOT,
            web_allowed_origins=("http://localhost:5173",),
        ),
        engine=engine,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=FakeAssetAccessSigner(),
        asset_object_store=FakePrivateObjectStore(),
        generation_task_publisher=FakeGenerationTaskPublisher(),
        text_understanding_provider=FakeTextUnderstandingProvider(),
        knowledge_http=knowledge_http,
    )
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer test-consultant-a"
    return client


@pytest.fixture(scope="module")
def http(pilot):  # noqa: F811
    engine, _, _ = pilot
    with _client(engine, KnowledgeHttpConfig(enabled=True, caller_id="consultant")) as client:
        yield client, engine


def test_endpoints_are_absent_unless_enabled(pilot):  # noqa: F811
    engine, _, _ = pilot
    with _client(engine, KnowledgeHttpConfig()) as client:
        assert client.get("/knowledge/releases/active").status_code == 404
        assert client.get("/health").status_code == 200


def test_bearer_authentication_is_required(http):
    client, _ = http
    response = client.get("/knowledge/releases/active", headers={"Authorization": ""})
    assert response.status_code == 401


def test_release_metadata_and_first_pin(http):
    client, _ = http
    active = client.get("/knowledge/releases/active").json()
    assert active["release_id"] == PILOT and len(active["checksum"]) == 64
    assert client.get(f"/knowledge/releases/{PILOT}").json()["checksum"] == active["checksum"]
    missing = client.get("/knowledge/releases/kb-9.9.9")
    assert missing.status_code == 404 and missing.json()["error"] == "release_not_found"


def test_claims_respect_purpose_policy_and_the_server_fixed_caller(http):
    client, _ = http
    base = f"/knowledge/releases/{PILOT}/entities/gem.corundum.ruby/claims"
    shown = client.get(base, params={"purpose": "display"})
    assert shown.status_code == 200
    body = shown.json()
    assert body["claims"] and all(c["release_id"] == PILOT for c in body["claims"])
    assert all(c["policy_revision_id"].startswith("policy-r1:") for c in body["claims"])
    # The HTTP caller is "consultant" by configuration; prompt belongs to the SO only.
    denied = client.get(base, params={"purpose": "prompt"})
    assert denied.status_code == 403 and denied.json()["error"] == "purpose_not_allowed"
    # "active" is not a pinned release for facts.
    assert client.get(base.replace(PILOT, "active"), params={"purpose": "display"}).status_code == (
        404
    )


def test_scope_and_attribute_filters(http):
    client, _ = http
    response = client.get(
        f"/knowledge/releases/{PILOT}/entities/gem.diamond/claims",
        params=[
            ("purpose", "display"),
            ("attribute", "diameter_at_weight"),
            ("scope", "carat_weight:1"),
        ],
    )
    claims = response.json()["claims"]
    assert [c["value"] for c in claims] == [{"num": "6.4"}] and claims[0]["approximate"]
    bad = client.get(
        f"/knowledge/releases/{PILOT}/entities/gem.diamond/claims",
        params={"purpose": "display", "scope": "carat_weight"},
    )
    assert bad.status_code == 422 and bad.json()["error"] == "invalid_request"
    unknown = client.get(
        f"/knowledge/releases/{PILOT}/entities/gem.unobtainium/claims",
        params={"purpose": "display"},
    )
    assert unknown.status_code == 404 and unknown.json()["error"] == "unknown_entity"


def test_terms_evaluation_rules_and_search(http):
    client, _ = http
    terms = client.get(f"/knowledge/releases/{PILOT}/terms", params={"text": "Карат"}).json()
    assert terms["ambiguous"] and {c["review_status"] for c in terms["candidates"]} == {"curated"}
    evaluation = client.post(
        f"/knowledge/releases/{PILOT}/evaluate-claim",
        json={
            "entity_id": "gem.corundum.ruby",
            "attribute_id": "specific_gravity",
            "value": {"num": "4.00"},
        },
    ).json()
    assert evaluation["result"] == "supported" and "allowed_uses" not in evaluation
    strict = client.post(
        f"/knowledge/releases/{PILOT}/evaluate-claim",
        json={"entity_id": "x", "attribute_id": "y", "value": {}, "unexpected": 1},
    )
    assert strict.status_code == 422
    rules = client.post(
        f"/knowledge/releases/{PILOT}/evaluate-rules",
        json={"spec": {"entities": ["gem.corundum.ruby"]}, "purpose": "validate_block"},
    )
    assert rules.status_code == 403
    hits = client.get(f"/knowledge/releases/{PILOT}/search", params={"q": "рубин"}).json()
    assert hits and all(hit["prompt_permission"] is False for hit in hits)


def test_http_reads_never_write(http):
    client, engine = http
    tables = ("design_session", "kb_change_log", "kb_active_release_log", "kb_release")
    with engine.connect() as db:
        before = {t: db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables}
    client.get("/knowledge/releases/active")
    client.get(f"/knowledge/releases/{PILOT}/terms", params={"text": "ruby"})
    client.get(
        f"/knowledge/releases/{PILOT}/entities/gem.corundum.ruby/claims",
        params={"purpose": "explain"},
    )
    client.post(
        f"/knowledge/releases/{PILOT}/evaluate-claim",
        json={
            "entity_id": "gem.corundum.ruby",
            "attribute_id": "mohs_hardness",
            "value": {"num": "9"},
        },
    )
    with engine.connect() as db:
        assert {t: db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables} == before
