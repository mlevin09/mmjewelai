"""Two distinct synthetic HTTP endpoints; never a claim of two deployed models."""

import json
from contextlib import contextmanager
from copy import deepcopy

import httpx
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
from test_conversation_model import context_inputs as context_inputs
from test_natural_turn import EN, Model, get, post, prepare, real_client
from test_professional_knowledge_http import real_config as real_config

from jewelai_api import create_app
from jewelai_api.conversation_profiles import ADAPTERS, select_profile
from jewelai_api.conversation_qwen import QwenConversationAdapter
from jewelai_api.settings import ArtifactVersions, RuntimeSettings, _conversation_config


def profiles():
    return [
        dict(
            profile_id=key,
            engine="llama_cpp",
            approved=True,
            endpoint=f"http://127.0.0.1:{port}/v1/chat/completions",
            model=f"fixture-{key}",
            model_sha256=digit * 64,
            runtime_build=f"test-only-{key}",
            context_tokens=4096,
            temperature=temperature,
        )
        for key, port, digit, temperature in [
            ("model-a", 18081, "1", 0.0),
            ("model-b", 18082, "2", 0.2),
        ]
    ]


class Endpoint:
    def __init__(self, profile):
        self.profile = profile
        self.calls = []
        self.unavailable = False

    def handle(self, request):
        assert str(request.url) == self.profile["endpoint"]
        packet = json.loads(request.content)
        assert packet["model"] == self.profile["model"]
        assert packet["temperature"] == self.profile["temperature"]
        data = json.loads(packet["messages"][1]["content"])
        self.calls.append(packet)
        if self.unavailable:
            return httpx.Response(503, content=b"private upstream diagnostic")
        if "arbitration" not in data:
            assert "source_parse" not in data and data["original_text"] == EN
            body = {
                "intent": "creation",
                "changes": [
                    {
                        "target": target,
                        "value": value,
                        "component": component,
                        "disposition": "selection",
                        "source_phrase": quote,
                    }
                    for target, value, component, quote in [
                        ("jewelry_type", "earrings", "product", "earrings"),
                        ("metal.material", "gold", "product_body", "gold"),
                        ("metal.color", "white", "product_body", "white"),
                        ("stone.material", "sapphire", "stone", "sapphires"),
                        ("stone.count", 2, "stone", "two"),
                    ]
                ],
            }
        else:
            body = {
                "text": "Your white gold earrings are saved. Are the two mentioned sapphires "
                "for the pair or for each earring?"
            }
        return httpx.Response(
            200,
            json={
                "model": self.profile["model"],
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
            },
        )


@contextmanager
def configured_client(engine, release, config):
    app = create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
            artifacts=ArtifactVersions(questions="2.0.0", rules="2.0.0"),
            prompt_enrichment=release,
            conversation=config,
        ),
        engine=engine,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=FakeAssetAccessSigner(),
        asset_object_store=FakePrivateObjectStore(),
        generation_task_publisher=FakeGenerationTaskPublisher(),
        text_understanding_provider=FakeTextUnderstandingProvider(),
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer test-owner-a"
        yield client, app


def test_active_profiles_a_b_a_route_and_read_actual_receipts_unchanged(
    engine, real_config, monkeypatch
):
    rows = profiles()
    endpoints = {r["endpoint"]: Endpoint(r) for r in rows}

    def adapter(config):
        return QwenConversationAdapter(
            config,
            client=httpx.Client(transport=httpx.MockTransport(endpoints[config.endpoint].handle)),
        )

    monkeypatch.setitem(ADAPTERS, "llama_cpp", adapter)
    monkeypatch.setenv("ST01_CONVERSATION_PROFILES_JSON", json.dumps(rows))
    monkeypatch.delenv("ST01_CONVERSATION_PROVIDER", raising=False)
    retained = []
    for active in ["model-a", "model-b", "model-a"]:
        monkeypatch.setenv("ST01_CONVERSATION_ACTIVE_PROFILE", active)
        with configured_client(engine, real_config, _conversation_config()) as (client, app):
            for sid, oid, body in retained:
                before = (
                    app.state.prompt_enrichment_service.repository.get_initial_conversation_turn(
                        sid, oid
                    )
                )
                assert get(client, sid, oid).json() == body
                assert (
                    app.state.prompt_enrichment_service.repository.get_initial_conversation_turn(
                        sid, oid
                    )
                    == before
                )
            sid, oid, _, request = prepare(client, app, "en", EN)
            response = post(client, sid, oid, request)
            assert response.status_code == 201, response.json()
            body = response.json()
            runtime = body["evidence"]["model_runtime"]
            assert body["delivered_reply"]["origin"] == "model"
            assert runtime["provider"] == body["delivered_reply"]["provider"] == "llama_cpp"
            assert runtime["model"] == body["delivered_reply"]["model"] == f"fixture-{active}"
            assert runtime["sampling"]["profile"] == active
            assert runtime["sampling"]["context_tokens"] == 4096
            assert "endpoint" not in runtime["sampling"]
            assert len(app.state.prompt_enrichment_service.repository.list_messages(sid, oid)) == 1
            assert post(client, sid, oid, request).json() == body
            retained.append((sid, oid, body))
    assert [len(endpoints[r["endpoint"]].calls) for r in rows] == [4, 2]
    # Existing historical qwen provider/pins remain readable under a different active profile.
    with real_client(engine, real_config, conversation_model=Model()) as (client, app, _):
        sid, oid, _, request = prepare(client, app, "en", EN)
        body = post(client, sid, oid, request).json()
    with configured_client(engine, real_config, select_profile(json.dumps(rows), "model-b")) as (
        client,
        app,
    ):
        assert get(client, sid, oid).json() == body
        other_sid, other_oid, before, request = prepare(client, app, "en", EN)
        endpoints[rows[1]["endpoint"]].unavailable = True
        result = post(client, other_sid, other_oid, request).json()
        assert result["delivered_reply"]["origin"] == "fallback"
        assert result["evidence"]["meaning_origin"] == "unavailable"
        assert result["current_revision"]["revision_id"] == str(before.revision_id)
        assert post(client, other_sid, other_oid, request).json() == result
    assert [len(endpoints[r["endpoint"]].calls) for r in rows] == [4, 4]


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "missing",
        "unapproved",
        "duplicate",
        "extra_secret",
        "remote_anonymous",
        "invalid_hash",
        "unknown_engine",
        "invalid_sampling",
        "stream",
        "retries",
        "empty_secret",
    ],
)
def test_profile_configuration_fails_closed(mutation):
    rows = deepcopy(profiles())
    active = "model-a"
    if mutation == "unknown":
        active = "absent"
    elif mutation == "missing":
        del rows[0]["runtime_build"]
    elif mutation == "unapproved":
        rows[0]["approved"] = False
    elif mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "extra_secret":
        rows[0]["api_key"] = "do-not-log"
    elif mutation == "remote_anonymous":
        rows[0]["endpoint"] = "http://10.0.0.2/v1/chat/completions"
    elif mutation == "invalid_hash":
        rows[0]["model_sha256"] = "unknown"
    elif mutation == "unknown_engine":
        rows[0]["engine"] = "made-up"
    elif mutation == "invalid_sampling":
        rows[0]["temperature"] = float("nan")
    elif mutation == "stream":
        rows[0]["stream"] = True
    elif mutation == "retries":
        rows[0]["max_attempts"] = 2
    elif mutation == "empty_secret":
        rows[0].update(
            endpoint="https://10.0.0.2/v1/chat/completions",
            auth_mode="bearer_env",
            auth_env="TEST_SECRET",
        )
    with pytest.raises(ValueError, match="Invalid, missing or unauthorized"):
        select_profile(json.dumps(rows), active, environment={})


def test_disabled_and_ambiguous_configuration(monkeypatch):
    monkeypatch.setenv("ST01_CONVERSATION_ACTIVE_PROFILE", "disabled")
    monkeypatch.setenv("ST01_CONVERSATION_PROVIDER", "qwen")
    monkeypatch.delenv("ST01_CONVERSATION_PROFILES_JSON", raising=False)
    assert _conversation_config() is None
    monkeypatch.setenv("ST01_CONVERSATION_ACTIVE_PROFILE", "model-a")
    monkeypatch.setenv("ST01_CONVERSATION_PROFILES_JSON", json.dumps(profiles()))
    with pytest.raises(ValueError, match="unambiguous"):
        _conversation_config()
    with pytest.raises(ValueError):
        select_profile('[{"profile_id":"a","profile_id":"b"}]', "a")


@pytest.mark.parametrize("auth", ["bearer_env", "google_id_token"])
def test_authenticated_profile_private_transport_and_safe_telemetry(
    auth, monkeypatch, context_inputs
):
    import logging

    from jewelai_api.conversation_model import build_conversation_context

    row = profiles()[0]
    row.update(endpoint="https://10.0.0.2/v1/chat/completions", auth_mode=auth)
    secret = "synthetic-secret-not-for-logs"
    if auth == "bearer_env":
        row["auth_env"] = "TEST_CONVERSATION_TOKEN"
        monkeypatch.setenv("TEST_CONVERSATION_TOKEN", secret)
    else:
        row["audience"] = "https://10.0.0.2"

        def credential(request, audience):
            assert audience == row["audience"]
            return secret

        monkeypatch.setattr("google.oauth2.id_token.fetch_id_token", credential)
    config = select_profile(json.dumps([row]), row["profile_id"])
    endpoint = Endpoint(row)

    def transport(request):
        assert request.headers["Authorization"] == "Bearer " + secret
        return endpoint.handle(request)

    records = []

    class Handler(logging.Handler):
        def emit(self, record):
            records.append(record.jewelai_fields)

    logger = logging.getLogger("jewelai.conversation")
    handler = Handler()
    logger.addHandler(handler)
    try:
        model = QwenConversationAdapter(
            config, client=httpx.Client(transport=httpx.MockTransport(transport))
        )
        context = build_conversation_context(**context_inputs, original_text=EN, locale="en")
        assert model.interpret(context).intent == "creation"
        assert len(records) == 1 and records[0]["outcome"] == "untrusted_draft_generated"
        assert records[0]["message_id"] == str(context.message_id)
        assert records[0]["latency_ms"] >= 0
        exported = json.dumps(records) + json.dumps(model.sampling_snapshot())
        assert secret not in exported and EN not in exported and row["endpoint"] not in exported
    finally:
        logger.removeHandler(handler)


def test_pending_reply_cannot_cross_runtime_identity_then_recovers(
    engine, real_config, monkeypatch
):
    from jewelai_persistence import EnrichmentIntegrityError

    rows = profiles()
    endpoints = {r["endpoint"]: Endpoint(r) for r in rows}

    def adapter(config):
        return QwenConversationAdapter(
            config,
            client=httpx.Client(transport=httpx.MockTransport(endpoints[config.endpoint].handle)),
        )

    monkeypatch.setitem(ADAPTERS, "llama_cpp", adapter)
    with configured_client(engine, real_config, select_profile(json.dumps(rows), "model-a")) as (
        client,
        app,
    ):
        sid, oid, _, request = prepare(client, app, "en", EN)
        repo = app.state.prompt_enrichment_service.repository

        def failed(**kwargs):
            raise EnrichmentIntegrityError("synthetic delivery write failure")

        monkeypatch.setattr(repo, "commit_initial_conversation_reply", failed)
        assert post(client, sid, oid, request).status_code == 500
        retained = repo.get_initial_conversation_turn(sid, oid)
        assert get(client, sid, oid).json()["delivery_status"] == "pending"
    with configured_client(engine, real_config, select_profile(json.dumps(rows), "model-b")) as (
        client,
        app,
    ):
        assert post(client, sid, oid, request).status_code == 409
        assert endpoints[rows[1]["endpoint"]].calls == []
        assert (
            app.state.prompt_enrichment_service.repository.get_initial_conversation_turn(sid, oid)
            == retained
        )
    with configured_client(engine, real_config, select_profile(json.dumps(rows), "model-a")) as (
        client,
        app,
    ):
        result = post(client, sid, oid, request)
        assert result.status_code == 200 and result.json()["delivered_reply"]["origin"] == "model"
        assert len(app.state.prompt_enrichment_service.repository.list_messages(sid, oid)) == 1
    with configured_client(engine, real_config, None) as (client, app):
        assert get(client, sid, oid).json() == result.json()
        other, organization, parent, request = prepare(client, app, "en", EN)
        disabled = post(client, other, organization, request).json()
        assert disabled["evidence"]["meaning_failure_code"] == "not_configured"
        assert disabled["delivered_reply"]["origin"] == "fallback"
        assert disabled["current_revision"]["revision_id"] == str(parent.revision_id)


@pytest.mark.parametrize("auth", ["bearer_env", "google_id_token"])
def test_missing_runtime_credential_never_sends_inference(auth, monkeypatch, context_inputs):
    from jewelai_api.conversation_model import build_conversation_context
    from jewelai_api.conversation_qwen import ConversationProviderError

    row = profiles()[0]
    row.update(endpoint="https://10.0.0.2/v1/chat/completions", auth_mode=auth)
    if auth == "bearer_env":
        row["auth_env"] = "TEST_CONVERSATION_TOKEN"
        monkeypatch.setenv("TEST_CONVERSATION_TOKEN", "synthetic-secret")
    else:
        row["audience"] = "https://10.0.0.2"

        def missing(*args):
            raise RuntimeError("synthetic-secret-not-for-logs")

        monkeypatch.setattr("google.oauth2.id_token.fetch_id_token", missing)
    config = select_profile(json.dumps([row]), row["profile_id"])
    monkeypatch.delenv("TEST_CONVERSATION_TOKEN", raising=False)
    calls = []

    def transport(request):
        calls.append(request)
        raise AssertionError("Credential failure must precede network access")

    adapter = QwenConversationAdapter(
        config, client=httpx.Client(transport=httpx.MockTransport(transport))
    )
    with pytest.raises(ConversationProviderError) as caught:
        adapter.interpret(
            build_conversation_context(**context_inputs, original_text=EN, locale="en")
        )
    assert caught.value.code == "credential_unavailable" and "secret" not in str(caught.value)
    assert calls == []
