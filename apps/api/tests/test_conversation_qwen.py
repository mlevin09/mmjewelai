"""Native HTTP contract tests; MockTransport is NOT real-model acceptance."""

import json
from dataclasses import replace

import httpx
import pytest
from test_conversation_model import context_inputs as context_inputs
from test_professional_knowledge_http import real_config as real_config

from jewelai_api.conversation_model import build_conversation_context
from jewelai_api.conversation_qwen import (
    ConversationProviderError,
    QwenConversationAdapter,
    QwenConversationConfig,
)
from jewelai_api.semantic_proposal import SemanticProposal


def config(**kwargs):
    return QwenConversationConfig(
        endpoint="http://127.0.0.1:8080/v1/chat/completions",
        model="qwen3-1.7b-q4_k_m",
        model_sha256="0" * 64,
        runtime_build="test-not-live",
        **kwargs,
    )


def answer(payload, *, finish="stop", model="qwen3-1.7b-q4_k_m"):
    return {
        "model": model,
        "choices": [
            {
                "finish_reason": finish,
                "message": {"content": json.dumps(payload, ensure_ascii=False)},
            }
        ],
    }


def test_two_phases_raw_independence_and_committed_context(context_inputs):
    context = build_conversation_context(
        **context_inputs, original_text="Хочу серьги.", locale="ru"
    )
    seen = []

    def respond(request):
        body = json.loads(request.content)
        data = json.loads(body["messages"][1]["content"])
        assert "authorization" not in request.headers
        assert data["original_text"] == context.original_text
        assert data["revision_id"] == str(context_inputs["committed_revision"].revision_id)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["max_tokens"] == 512
        assert {
            k: body[k]
            for k in (
                "temperature",
                "top_p",
                "top_k",
                "min_p",
                "presence_penalty",
                "repeat_penalty",
                "seed",
                "cache_prompt",
            )
        } == {
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.0,
            "presence_penalty": 1.5,
            "repeat_penalty": 1.0,
            "seed": 20261111,
            "cache_prompt": False,
        }
        assert not body["stream"] and "tools" not in body
        if not seen:
            assert "arbitration" not in data and "source_parse" not in data
            seen.append(data)
            return httpx.Response(
                200,
                json=answer(
                    {
                        "intent": "creation",
                        "changes": [],
                    }
                ),
            )
        seen.append(data)
        assert data["arbitration"]["decisions"][0]["outcome"] == "CLARIFY"
        return httpx.Response(200, json=answer({"text": "Как распределить камни?"}))

    model = QwenConversationAdapter(
        config(), client=httpx.Client(transport=httpx.MockTransport(respond))
    )
    proposal = model.interpret(context)
    assert isinstance(proposal, SemanticProposal)
    reply = model.draft_reply(
        replace(
            context,
            semantic_evidence_json=json.dumps(
                {
                    "decisions": [{"proposal_id": "p0", "outcome": "CLARIFY"}],
                    "meaning": {
                        "changes": [
                            {
                                "proposal_id": "p0",
                                "target": "stone.count",
                                "value": 2,
                                "component": "stone",
                                "quantity_scope": None,
                            }
                        ]
                    },
                }
            ),
        )
    )
    assert reply.provider == "qwen" and reply.text == "Как распределить камни?"
    assert len(seen) == 2


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "upstream_auth"),
        (403, "upstream_permission"),
        (404, "upstream_not_found"),
        (429, "upstream_rate_limited"),
        (500, "upstream_5xx"),
        (302, "upstream_other"),
    ],
)
def test_safe_status_single_attempt_no_body_or_redirect(context_inputs, status, code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, text="private-provider-body", headers={"location": "https://example.com"}
        )

    model = QwenConversationAdapter(
        config(), client=httpx.Client(transport=httpx.MockTransport(respond))
    )
    context = build_conversation_context(**context_inputs, original_text="Hello", locale="en")
    with pytest.raises(ConversationProviderError) as error:
        model.interpret(context)
    assert error.value.code == code
    assert "private-provider-body" not in str(error.value) and len(calls) == 1


@pytest.mark.parametrize(
    "error,code",
    [(httpx.ReadTimeout, "upstream_timeout"), (httpx.ConnectError, "upstream_connection")],
)
def test_network_failure_never_exposes_exception(context_inputs, error, code):
    def respond(request):
        raise error("sensitive details", request=request)

    model = QwenConversationAdapter(
        config(), client=httpx.Client(transport=httpx.MockTransport(respond))
    )
    context = build_conversation_context(**context_inputs, original_text="Hello", locale="en")
    with pytest.raises(ConversationProviderError) as caught:
        model.interpret(context)
    assert caught.value.code == code and "sensitive" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        answer({}, finish="length"),
        answer({}, model="another-model"),
        answer({"write_state": True}),
        {"choices": []},
        {
            "model": "qwen3-1.7b-q4_k_m",
            "choices": [
                {"finish_reason": "stop", "message": {"content": "{}", "tool_calls": [{}]}}
            ],
        },
    ],
)
def test_incomplete_invalid_or_injected_output_fails_closed(context_inputs, payload):
    context = build_conversation_context(**context_inputs, original_text="Hello", locale="en")
    model = QwenConversationAdapter(
        config(),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
    )
    with pytest.raises(ConversationProviderError):
        model.interpret(context)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.openai.com/v1/chat/completions",
        "http://169.254.169.254/v1/chat/completions",
        "http://127.0.0.1:8080/v1/chat/completions?key=secret",
        "http://user:secret@127.0.0.1/v1/chat/completions",
        "http://0.0.0.0:8080/v1/chat/completions",
    ],
)
def test_no_external_provider_metadata_or_credential_urls(endpoint):
    with pytest.raises(ValueError):
        replace(config(), endpoint=endpoint)


def test_explicit_configuration_default_disabled_no_google_key(monkeypatch):
    from jewelai_api.settings import _conversation_config

    monkeypatch.delenv("ST01_CONVERSATION_PROVIDER", raising=False)
    assert _conversation_config() is None
    monkeypatch.setenv("ST01_CONVERSATION_PROVIDER", "qwen")
    with pytest.raises(ValueError):
        _conversation_config()
    for name, value in {
        "ENDPOINT": config().endpoint,
        "MODEL": config().model,
        "MODEL_SHA256": config().model_sha256,
        "RUNTIME_BUILD": config().runtime_build,
    }.items():
        monkeypatch.setenv("ST01_CONVERSATION_" + name, value)
    assert _conversation_config() == config()
