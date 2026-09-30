import base64
import inspect
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx2
import openai
import pytest
from jewelai_domain import DesignRevision
from jewelai_model_gateway import (
    GatewayTimeoutError,
    GatewayUnavailableError,
    GenerationConfiguration,
    GenerationRequest,
    ImageGenerationEditInput,
    ImageGenerationExecutor,
    ImageGenerationGateway,
    InvalidProviderResponseError,
    ProviderRejectedError,
    validate_generation_execution,
)
from jewelai_prompts import compile_prompt, load_prompt_templates

from jewelai_model_gateway_openai import (
    OpenAIImageGenerationAdapter,
    OpenAIImageProviderConfig,
)

ROOT = Path(__file__).resolve().parents[3]
MODEL = "gpt-image-2.5-sunburst-2026-09-08"
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
PROMPT_ID = UUID("22222222-2222-4222-8222-222222222222")
PNG = b"\x89PNG\r\n\x1a\ntransient-image"


class FakeImages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.images = FakeImages(response, error)


def response_for(*payloads):
    return SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(payload).decode()) for payload in payloads]
    )


@pytest.fixture(scope="module")
def compiled_prompt():
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    return compile_prompt(revision, load_prompt_templates(ROOT / "data/prompts/v1.0.0.json"))


def request_for(compiled_prompt, *, output_count=1, provider="openai", model=MODEL):
    return GenerationRequest(
        generation_run_id=RUN_ID,
        prompt_revision_id=PROMPT_ID,
        compiled_prompt=compiled_prompt,
        provider=provider,
        model=model,
        configuration=GenerationConfiguration(output_count=output_count),
    )


def adapter_for(client, **config_changes):
    return OpenAIImageGenerationAdapter(
        OpenAIImageProviderConfig(allowed_models=(MODEL,), **config_changes), client=client
    )


def test_exact_request_mapping_uses_immutable_prompt_png_and_no_url_option(compiled_prompt):
    client = FakeClient(response_for(PNG))
    request = request_for(compiled_prompt)

    execution = adapter_for(client).execute(request)

    assert client.images.calls == [
        {
            "model": MODEL,
            "prompt": compiled_prompt.prompt_text,
            "n": 1,
            "output_format": "png",
        }
    ]
    assert execution.result.model == MODEL
    assert execution.result.provider_request_id is None
    assert execution.result.outputs[0].provider_output_id is None
    assert execution.outputs[0].content == PNG
    assert "response_format" not in client.images.calls[0]
    assert "url" not in client.images.calls[0]


def test_image_conditioned_edit_is_rejected_without_text_only_fallback(compiled_prompt):
    client = FakeClient(response_for(PNG))
    edit = ImageGenerationEditInput(
        source_asset_id=UUID("33333333-3333-4333-8333-333333333333"),
        declared_content_type="image/png",
        content_hash="a" * 64,
        change_request="Make the stone larger.",
        content=PNG,
    )
    with pytest.raises(ProviderRejectedError):
        adapter_for(client).execute(request_for(compiled_prompt), edit_input=edit)
    assert client.images.calls == []


def test_adapter_is_executor_only_and_cannot_discard_outputs_through_legacy_gateway(
    compiled_prompt,
):
    client = FakeClient(response_for(PNG))
    adapter = adapter_for(client)
    assert isinstance(adapter, ImageGenerationExecutor)
    assert not isinstance(adapter, ImageGenerationGateway)
    assert not hasattr(adapter, "generate")
    assert client.images.calls == []


@pytest.mark.parametrize("output_count", [1, 2, 3, 4])
def test_multiple_outputs_are_exact_contiguous_and_aligned(compiled_prompt, output_count):
    payloads = tuple(PNG + bytes([ordinal]) for ordinal in range(1, output_count + 1))
    request = request_for(compiled_prompt, output_count=output_count)
    execution = adapter_for(FakeClient(response_for(*payloads))).execute(request)

    assert validate_generation_execution(request, execution) == execution
    assert tuple(item.ordinal for item in execution.result.outputs) == tuple(
        range(1, output_count + 1)
    )
    assert tuple(item.content for item in execution.outputs) == payloads


@pytest.mark.parametrize(
    "item",
    [
        SimpleNamespace(b64_json="not+strict/%%%"),
        SimpleNamespace(b64_json="YQ="),
        SimpleNamespace(b64_json=""),
        SimpleNamespace(),
        SimpleNamespace(b64_json=None),
    ],
)
def test_strict_base64_rejects_invalid_empty_or_missing_content(compiled_prompt, item):
    client = FakeClient(SimpleNamespace(data=[item]))
    with pytest.raises(InvalidProviderResponseError):
        adapter_for(client).execute(request_for(compiled_prompt))


def test_output_size_is_bounded_before_and_after_decode(compiled_prompt):
    request = request_for(compiled_prompt)
    for encoded in ("A" * 17, base64.b64encode(b"123456789").decode()):
        client = FakeClient(SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)]))
        with pytest.raises(InvalidProviderResponseError):
            adapter_for(client, max_output_bytes=8).execute(request)


@pytest.mark.parametrize(
    "provider,model",
    [("other", MODEL), ("openai", "gpt-image-not-allowlisted")],
)
def test_provider_and_model_allowlist_fail_before_provider_call(compiled_prompt, provider, model):
    client = FakeClient(response_for(PNG))
    with pytest.raises(ProviderRejectedError):
        adapter_for(client).execute(request_for(compiled_prompt, provider=provider, model=model))
    assert client.images.calls == []


def sdk_request():
    return httpx2.Request("POST", "https://api.openai.test/v1/images/generations")


def sdk_status_error(error_type, status_code, secret):
    response = httpx2.Response(status_code, request=sdk_request())
    return error_type(secret, response=response, body={"secret": secret})


@pytest.mark.parametrize(
    "error,expected,classification,status_code",
    [
        (
            sdk_status_error(openai.AuthenticationError, 401, "provider-secret"),
            GatewayUnavailableError,
            "upstream_auth",
            401,
        ),
        (
            sdk_status_error(openai.PermissionDeniedError, 403, "provider-secret"),
            GatewayUnavailableError,
            "upstream_permission",
            403,
        ),
        (
            sdk_status_error(openai.NotFoundError, 404, "provider-secret"),
            ProviderRejectedError,
            "upstream_not_found",
            404,
        ),
        (
            sdk_status_error(openai.RateLimitError, 429, "provider-secret"),
            GatewayUnavailableError,
            "upstream_rate_limited",
            429,
        ),
        (
            openai.APITimeoutError(sdk_request()),
            GatewayTimeoutError,
            "upstream_timeout",
            None,
        ),
        (
            openai.APIConnectionError(message="provider-secret", request=sdk_request()),
            GatewayUnavailableError,
            "upstream_connection",
            None,
        ),
        (
            sdk_status_error(openai.InternalServerError, 500, "provider-secret"),
            GatewayUnavailableError,
            "upstream_5xx",
            500,
        ),
        (
            openai.OpenAIError("provider-secret"),
            GatewayUnavailableError,
            "upstream_other",
            None,
        ),
    ],
)
def test_sdk_errors_emit_bounded_diagnostics_and_preserve_gateway_mapping(
    compiled_prompt,
    error,
    expected,
    classification,
    status_code,
):
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("jewelai.generation.openai")
    handler = Capture()
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with pytest.raises(expected) as raised:
            adapter_for(FakeClient(error=error)).execute(request_for(compiled_prompt))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)

    assert "provider-secret" not in str(raised.value)
    assert len(records) == 1
    assert records[0].getMessage() == "openai generation upstream failure"
    fields = records[0].jewelai_fields
    assert fields == {
        "event": "openai_generation_upstream_failure",
        "generation_run_id": str(RUN_ID),
        "upstream_classification": classification,
        **({"upstream_http_status": status_code} if status_code is not None else {}),
    }
    serialized = json.dumps(fields)
    assert "provider-secret" not in serialized
    assert "prompt" not in serialized


def test_bad_request_diagnostic_preserves_provider_rejected_mapping(compiled_prompt):
    error = sdk_status_error(openai.BadRequestError, 400, "provider-secret")
    with pytest.raises(ProviderRejectedError) as raised:
        adapter_for(FakeClient(error=error)).execute(request_for(compiled_prompt))
    assert "provider-secret" not in str(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(data=None),
        SimpleNamespace(data=[]),
        SimpleNamespace(data=[SimpleNamespace(b64_json="unused"), SimpleNamespace()]),
        SimpleNamespace(data=[SimpleNamespace(url="https://provider.example/image")]),
    ],
)
def test_malformed_response_and_url_only_output_fail_closed(compiled_prompt, response):
    with pytest.raises(InvalidProviderResponseError):
        adapter_for(FakeClient(response)).execute(request_for(compiled_prompt))


def test_default_client_construction_disables_retries_and_bounds_timeout(monkeypatch):
    captured = {}

    class CapturedClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("jewelai_model_gateway_openai.adapter.OpenAI", CapturedClient)
    OpenAIImageGenerationAdapter(OpenAIImageProviderConfig(allowed_models=(MODEL,)))
    assert captured == {"timeout": 180, "max_retries": 0}
    assert "api_key" not in captured


def test_config_is_bounded_non_secret_and_adapter_has_no_url_fetcher():
    with pytest.raises(ValueError):
        OpenAIImageProviderConfig(allowed_models=())
    with pytest.raises(ValueError):
        OpenAIImageProviderConfig(allowed_models=(MODEL,), timeout_seconds=0)
    with pytest.raises(ValueError):
        OpenAIImageProviderConfig(allowed_models=(MODEL,), timeout_seconds=601)
    with pytest.raises(ValueError):
        OpenAIImageProviderConfig(allowed_models=(MODEL,), max_output_bytes=20 * 1024 * 1024 + 1)
    source = inspect.getsource(OpenAIImageGenerationAdapter)
    assert "requests.get" not in source
    assert "httpx" not in source
    assert "urlopen" not in source


def test_openai_sdk_import_is_isolated_to_provider_adapter_package():
    source_roots = (
        ROOT / "packages/model_gateway/src",
        ROOT / "packages/assets/src",
        ROOT / "packages/persistence/src",
        ROOT / "workers/generation/src",
    )
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            source = path.read_text()
            assert "import openai" not in source
            assert "from openai" not in source
