import json

import httpx
import pytest
from jewelai_parser import ParserTarget

from jewelai_text_understanding_google import (
    GoogleTextUnderstandingAdapter,
    GoogleTextUnderstandingConfig,
    TextUnderstandingInvalidResponseError,
    TextUnderstandingRejectedError,
    TextUnderstandingTimeoutError,
    TextUnderstandingUnavailableError,
)

API_KEY = "test-google-key"


def response(candidate):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(candidate)}]}}]}


def adapter(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GoogleTextUnderstandingAdapter(
        GoogleTextUnderstandingConfig(model="gemini-3.1-flash-lite"),
        api_key=API_KEY,
        client=client,
    )


@pytest.mark.parametrize(
    ("message", "locale", "updates"),
    [
        (
            "I want a white-gold ring with an oval center stone.",
            "en",
            [
                {"target": "jewelry_type", "value": {"kind": "term", "text": "ring"}},
                {"target": "metal.color", "value": {"kind": "term", "text": "white gold"}},
                {"target": "center_stone.shape", "value": {"kind": "term", "text": "oval"}},
            ],
        ),
        (
            "Хочу кольцо из белого золота с овальным центральным камнем.",
            "ru",
            [
                {"target": "jewelry_type", "value": {"kind": "term", "text": "кольцо"}},
                {"target": "metal.color", "value": {"kind": "term", "text": "белое золото"}},
                {"target": "center_stone.shape", "value": {"kind": "term", "text": "овальный"}},
            ],
        ),
    ],
)
def test_understands_en_and_ru_as_untrusted_candidates(message, locale, updates):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(
            200,
            json=response({"schema_version": "1.0.0", "updates": updates}),
        )

    candidate = adapter(handler).understand(message, locale)

    assert [item.target for item in candidate.updates] == [
        ParserTarget(item["target"]) for item in updates
    ]
    assert all(item.target != ParserTarget.CENTER_STONE_DIMENSIONS for item in candidate.updates)
    request = sent[0]
    assert request.url.path.endswith("/models/gemini-3.1-flash-lite:generateContent")
    assert request.url.query == b""
    assert request.headers["x-goog-api-key"] == API_KEY
    payload = json.loads(request.content)
    assert payload["generationConfig"]["temperature"] == 0
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    schema = payload["generationConfig"]["responseJsonSchema"]
    assert schema["$defs"]["ParserTarget"]["enum"] == [target.value for target in ParserTarget]
    serialized_schema = json.dumps(schema)
    for unsupported in (
        '"const"',
        '"default"',
        '"discriminator"',
        '"exclusiveMinimum"',
        '"pattern"',
    ):
        assert unsupported not in serialized_schema
    assert message in payload["contents"][0]["parts"][0]["text"]
    assert locale in payload["contents"][0]["parts"][0]["text"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"candidates": []},
        {"candidates": [{"content": {"parts": []}}]},
        response(
            {
                "schema_version": "1.0.0",
                "updates": [{"target": "admin", "value": {"kind": "term", "text": "x"}}],
            }
        ),
        {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
    ],
)
def test_malformed_or_unknown_provider_output_fails_closed(body):
    provider = adapter(lambda _: httpx.Response(200, json=body))
    with pytest.raises(TextUnderstandingInvalidResponseError):
        provider.understand("A ring", "en")


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, TextUnderstandingRejectedError),
        (401, TextUnderstandingRejectedError),
        (429, TextUnderstandingUnavailableError),
        (500, TextUnderstandingUnavailableError),
    ],
)
def test_safe_http_error_mapping(status, error):
    provider = adapter(lambda _: httpx.Response(status, text=f"secret {API_KEY}"))
    with pytest.raises(error) as caught:
        provider.understand("A ring", "en")
    assert API_KEY not in str(caught.value)


def test_timeout_and_connection_failures_are_typed_and_not_retried():
    calls = 0

    def timeout(_):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("secret response")

    with pytest.raises(TextUnderstandingTimeoutError):
        adapter(timeout).understand("A ring", "en")
    assert calls == 1

    def unavailable(request):
        raise httpx.ConnectError("secret host", request=request)

    with pytest.raises(TextUnderstandingUnavailableError):
        adapter(unavailable).understand("A ring", "en")


def test_api_key_is_not_exposed_by_config_or_adapter_repr():
    provider = adapter(lambda _: httpx.Response(500))
    assert API_KEY not in repr(provider)
    assert API_KEY not in repr(provider.config)


def test_thought_parts_are_ignored_before_candidate_validation():
    body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"thought": True, "text": "internal reasoning"},
                        {
                            "text": json.dumps(
                                {
                                    "schema_version": "1.0.0",
                                    "updates": [
                                        {
                                            "target": "jewelry_type",
                                            "value": {"kind": "term", "text": "ring"},
                                        }
                                    ],
                                }
                            )
                        },
                    ]
                }
            }
        ]
    }
    candidate = adapter(lambda _: httpx.Response(200, json=body)).understand("A ring", "en")
    assert candidate.updates[0].target is ParserTarget.JEWELRY_TYPE
