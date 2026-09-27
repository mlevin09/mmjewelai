import base64
import inspect
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from jewelai_domain import DesignRevision
from jewelai_model_gateway import (
    GatewayTimeoutError,
    GatewayUnavailableError,
    GenerationConfiguration,
    GenerationRequest,
    ImageGenerationExecutor,
    InvalidProviderResponseError,
    ProviderRejectedError,
    validate_generation_execution,
)
from jewelai_prompts import compile_prompt, load_prompt_templates

from jewelai_model_gateway_google import (
    GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT,
    GOOGLE_IMAGE_MODELS,
    GoogleGenerativeLanguageConfig,
    GoogleGenerativeLanguageImageAdapter,
)
from jewelai_model_gateway_google import adapter as google_adapter_module

ROOT = Path(__file__).resolve().parents[3]
MODEL = "gemini-3.1-flash-lite-image"
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
PROMPT_ID = UUID("22222222-2222-4222-8222-222222222222")
API_KEY = "google-secret-key-for-tests"
PNG = b"\x89PNG\r\n\x1a\ntransient-google-image"


@pytest.fixture(scope="module")
def compiled_prompt():
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    return compile_prompt(revision, load_prompt_templates(ROOT / "data/prompts/v1.0.0.json"))


def generation_request(compiled_prompt, **overrides):
    values = {
        "generation_run_id": RUN_ID,
        "prompt_revision_id": PROMPT_ID,
        "compiled_prompt": compiled_prompt,
        "provider": "google",
        "model": MODEL,
        "configuration": GenerationConfiguration(output_count=1),
    }
    values.update(overrides)
    return GenerationRequest(**values)


def response_body(
    content=PNG,
    *,
    mime_type="image/png",
    prefix_parts=(),
):
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        *prefix_parts,
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(content).decode(),
                            }
                        },
                    ]
                }
            }
        ]
    }


def adapter_for(handler, *, config=None, api_key=API_KEY):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GoogleGenerativeLanguageImageAdapter(
        config or GoogleGenerativeLanguageConfig(allowed_models=(MODEL,)),
        api_key=api_key,
        client=client,
    )


def test_exact_endpoint_header_and_request_shape(compiled_prompt):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=response_body())

    request = generation_request(compiled_prompt)
    execution = adapter_for(handler).execute(request)
    sent = captured[0]
    assert str(sent.url) == GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT.format(model=MODEL)
    assert sent.headers["x-goog-api-key"] == API_KEY
    assert API_KEY not in str(sent.url)
    assert sent.headers["content-type"] == "application/json"
    assert json.loads(sent.content) == {
        "contents": [{"parts": [{"text": compiled_prompt.prompt_text}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    assert len(captured) == 1
    assert validate_generation_execution(request, execution) == execution
    assert execution.result.generation_run_id == RUN_ID
    assert execution.result.provider == "google"
    assert execution.result.model == MODEL
    assert execution.outputs[0].content == PNG
    assert execution.outputs[0].declared_content_type == "image/png"


def test_text_and_thought_parts_are_ignored(compiled_prompt):
    body = response_body(
        prefix_parts=(
            {"text": "provider commentary"},
            {"thought": True, "text": "provider thought"},
        )
    )
    execution = adapter_for(lambda request: httpx.Response(200, json=body)).execute(
        generation_request(compiled_prompt)
    )
    assert execution.outputs[0].content == PNG


@pytest.mark.parametrize("model", sorted(GOOGLE_IMAGE_MODELS))
def test_exact_supported_model_allowlist_accepts_each_model(compiled_prompt, model):
    adapter = adapter_for(
        lambda request: httpx.Response(200, json=response_body()),
        config=GoogleGenerativeLanguageConfig(allowed_models=(model,)),
    )
    result = adapter.execute(generation_request(compiled_prompt, model=model))
    assert result.result.model == model


@pytest.mark.parametrize(
    "models",
    [(), (MODEL, MODEL), ("gemini-latest",), ("gemini-3.1-flash-lite",)],
)
def test_config_rejects_empty_duplicate_or_unknown_model_sets(models):
    with pytest.raises(ValueError):
        GoogleGenerativeLanguageConfig(allowed_models=models)


def test_wrong_provider_unknown_model_and_multiple_outputs_are_rejected_without_call(
    compiled_prompt,
):
    calls = []
    adapter = adapter_for(lambda request: calls.append(request))
    requests = (
        generation_request(compiled_prompt, provider="openai"),
        generation_request(compiled_prompt, model="unknown-image-model"),
        generation_request(
            compiled_prompt,
            configuration=GenerationConfiguration(output_count=2),
        ),
    )
    for request in requests:
        with pytest.raises(ProviderRejectedError):
            adapter.execute(request)
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"candidates": []},
        {"candidates": [{}]},
        {"candidates": [{"content": {}}]},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"text": "only text"}]}}]},
        {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png"}}]}}]},
    ],
)
def test_missing_candidate_content_parts_or_inline_data_is_invalid(compiled_prompt, body):
    adapter = adapter_for(lambda request: httpx.Response(200, json=body))
    with pytest.raises(InvalidProviderResponseError):
        adapter.execute(generation_request(compiled_prompt))


@pytest.mark.parametrize("encoded", ["not base64!", "", "===="])
def test_invalid_or_empty_base64_is_rejected(compiled_prompt, encoded):
    body = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": encoded}}]}}
        ]
    }
    with pytest.raises(InvalidProviderResponseError):
        adapter_for(lambda request: httpx.Response(200, json=body)).execute(
            generation_request(compiled_prompt)
        )


def test_encoded_and_decoded_size_limits_are_enforced(compiled_prompt):
    config = GoogleGenerativeLanguageConfig(allowed_models=(MODEL,), max_output_bytes=16)
    encoded_too_large = response_body(PNG)
    decoded_too_large = response_body(b"\x89PNG\r\n\x1a\n123456789")
    for body in (encoded_too_large, decoded_too_large):
        with pytest.raises(InvalidProviderResponseError):
            adapter_for(
                lambda request, body=body: httpx.Response(200, json=body),
                config=config,
            ).execute(generation_request(compiled_prompt))


@pytest.mark.parametrize("mime_type", ["image/jpeg", "image/webp", "text/plain", None])
def test_wrong_mime_type_is_rejected(compiled_prompt, mime_type):
    body = response_body(PNG, mime_type=mime_type)
    with pytest.raises(InvalidProviderResponseError):
        adapter_for(lambda request: httpx.Response(200, json=body)).execute(
            generation_request(compiled_prompt)
        )


def test_non_png_bytes_cannot_be_relabelled_as_png(compiled_prompt):
    body = response_body(b"\xff\xd8\xffjpeg-data", mime_type="image/png")
    with pytest.raises(InvalidProviderResponseError):
        adapter_for(lambda request: httpx.Response(200, json=body)).execute(
            generation_request(compiled_prompt)
        )


def test_multiple_inline_images_are_rejected(compiled_prompt):
    inline = response_body()["candidates"][0]["content"]["parts"][0]
    body = {"candidates": [{"content": {"parts": [inline, inline]}}]}
    with pytest.raises(InvalidProviderResponseError):
        adapter_for(lambda request: httpx.Response(200, json=body)).execute(
            generation_request(compiled_prompt)
        )


def test_timeout_and_connection_failures_map_safely_and_call_once(compiled_prompt):
    request = generation_request(compiled_prompt)
    for error_type, expected in (
        (httpx.ReadTimeout, GatewayTimeoutError),
        (httpx.ConnectError, GatewayUnavailableError),
    ):
        calls = 0

        def handler(http_request, error_type=error_type):
            nonlocal calls
            calls += 1
            raise error_type("sensitive provider failure", request=http_request)

        with pytest.raises(expected) as caught:
            adapter_for(handler).execute(request)
        assert calls == 1
        assert "sensitive provider failure" not in str(caught.value)
        assert API_KEY not in str(caught.value)


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, ProviderRejectedError),
        (401, ProviderRejectedError),
        (403, ProviderRejectedError),
        (429, GatewayUnavailableError),
        (500, GatewayUnavailableError),
        (503, GatewayUnavailableError),
    ],
)
def test_http_status_mapping_is_safe_and_never_retries(compiled_prompt, status, expected):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            text=f"secret={API_KEY}&image={base64.b64encode(PNG).decode()}",
        )

    with pytest.raises(expected) as caught:
        adapter_for(handler).execute(generation_request(compiled_prompt))
    assert calls == 1
    assert API_KEY not in str(caught.value)
    assert "iVBOR" not in str(caught.value)


def test_malformed_json_is_invalid_provider_response(compiled_prompt):
    response = httpx.Response(
        200,
        content=b"not-json",
        headers={"content-type": "application/json"},
    )
    with pytest.raises(InvalidProviderResponseError):
        adapter_for(lambda request: response).execute(generation_request(compiled_prompt))


def test_api_key_is_exact_required_and_absent_from_repr_and_config():
    config = GoogleGenerativeLanguageConfig(allowed_models=(MODEL,))
    adapter = adapter_for(lambda request: httpx.Response(200, json=response_body()))
    assert API_KEY not in repr(config)
    assert API_KEY not in repr(adapter)
    for invalid in ("", f" {API_KEY}", f"{API_KEY} ", f" {API_KEY} "):
        with pytest.raises(ValueError) as caught:
            adapter_for(lambda request: None, api_key=invalid)
        assert API_KEY not in str(caught.value)


@pytest.mark.parametrize("timeout", [0, 601, True])
def test_timeout_is_bounded(timeout):
    with pytest.raises(ValueError):
        GoogleGenerativeLanguageConfig(allowed_models=(MODEL,), timeout_seconds=timeout)


def test_adapter_satisfies_executor_contract():
    assert isinstance(
        adapter_for(lambda request: httpx.Response(200, json=response_body())),
        ImageGenerationExecutor,
    )


def test_adapter_is_plain_rest_without_vertex_or_service_account_authentication():
    source = inspect.getsource(google_adapter_module)
    assert "vertex" not in source.lower()
    assert "service_account" not in source
    assert "google.cloud" not in source
    assert "?key=" not in source
