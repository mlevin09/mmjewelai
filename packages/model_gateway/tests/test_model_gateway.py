import inspect
import json
from pathlib import Path
from uuid import UUID

import pytest
from jewelai_domain import DesignRevision
from jewelai_prompts import compile_prompt, load_prompt_templates
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_model_gateway import (
    MODEL_GATEWAY_SCHEMA_VERSION,
    GatewayContractViolationError,
    GeneratedOutputDescriptor,
    GenerationConfiguration,
    GenerationRequest,
    GenerationResult,
    ImageGenerationGateway,
    validate_generation_result,
)
from jewelai_model_gateway.schema import model_gateway_json_schema

ROOT = Path(__file__).resolve().parents[3]
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
PROMPT_ID = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture(scope="module")
def generation_request():
    revision = DesignRevision.model_validate_json(
        (ROOT / "specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
    )
    templates = load_prompt_templates(ROOT / "data/prompts/v1.0.0.json")
    return GenerationRequest(
        generation_run_id=RUN_ID,
        prompt_revision_id=PROMPT_ID,
        compiled_prompt=compile_prompt(revision, templates),
        provider="test",
        model="deterministic-image-v1",
        configuration=GenerationConfiguration(output_count=2),
    )


def result_for(generation_request, **changes):
    payload = {
        "generation_run_id": generation_request.generation_run_id,
        "provider": generation_request.provider,
        "model": generation_request.model,
        "provider_request_id": "test-request-1",
        "outputs": (
            GeneratedOutputDescriptor(ordinal=1, provider_output_id="output-1"),
            GeneratedOutputDescriptor(ordinal=2, provider_output_id="output-2"),
        ),
    }
    payload.update(changes)
    return GenerationResult(**payload)


def test_request_and_result_validate_and_preserve_compiled_prompt(generation_request):
    result = result_for(generation_request)
    assert (
        generation_request.schema_version == result.schema_version == MODEL_GATEWAY_SCHEMA_VERSION
    )
    assert generation_request.compiled_prompt.locked_constraints
    assert validate_generation_result(generation_request, result) == result


@pytest.mark.parametrize("field,value", [("provider", "Bad Provider"), ("model", "-bad")])
def test_invalid_provider_and_model_identifiers_rejected(generation_request, field, value):
    payload = generation_request.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(payload)


@pytest.mark.parametrize("count", [0, 5])
def test_output_count_is_bounded(count):
    with pytest.raises(ValidationError):
        GenerationConfiguration(output_count=count)


def test_extra_fields_rejected(generation_request):
    payload = generation_request.model_dump(mode="json")
    payload["api_key"] = "forbidden"
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(payload)


@pytest.mark.parametrize(
    "outputs",
    [
        ({"ordinal": 2, "media_type": "image"},),
        (
            {"ordinal": 1, "provider_output_id": "same", "media_type": "image"},
            {"ordinal": 2, "provider_output_id": "same", "media_type": "image"},
        ),
    ],
)
def test_result_rejects_invalid_output_order_and_duplicate_ids(generation_request, outputs):
    with pytest.raises(ValidationError):
        GenerationResult(
            generation_run_id=generation_request.generation_run_id,
            provider=generation_request.provider,
            model=generation_request.model,
            outputs=outputs,
        )


@pytest.mark.parametrize(
    "provider_output_id",
    [
        "https://provider.example/image",
        "http://provider.example/image",
        "data:image/png;base64,AAAA",
        "file:///tmp/image.png",
        "blob:abc123",
        "ftp://provider.example/image",
        "gs://bucket/object",
        "s3://bucket/object",
        "../relative/path.png",
        "/absolute/path.png",
        "output/id",
        r"output\id",
        "id?token=abc",
        "output id",
    ],
)
def test_output_descriptor_rejects_non_opaque_provider_output_ids(provider_output_id):
    with pytest.raises(ValidationError):
        GeneratedOutputDescriptor(ordinal=1, provider_output_id=provider_output_id)


@pytest.mark.parametrize(
    "provider_output_id",
    ["output-123", "image_001", "provider.asset.v1", "ABC123", "a", "A" * 240],
)
def test_output_descriptor_accepts_opaque_provider_output_ids(provider_output_id):
    descriptor = GeneratedOutputDescriptor(ordinal=1, provider_output_id=provider_output_id)

    assert descriptor.provider_output_id == provider_output_id


def test_output_descriptor_rejects_provider_output_id_over_max_length():
    with pytest.raises(ValidationError):
        GeneratedOutputDescriptor(ordinal=1, provider_output_id="A" * 241)


def test_output_descriptor_rejects_partial_dimensions():
    with pytest.raises(ValidationError):
        GeneratedOutputDescriptor(ordinal=1, width=1024)


@pytest.mark.parametrize(
    "changes",
    [
        {"generation_run_id": UUID("33333333-3333-4333-8333-333333333333")},
        {"provider": "other"},
        {"model": "other-model"},
        {"outputs": (GeneratedOutputDescriptor(ordinal=1),)},
    ],
)
def test_untrusted_result_lineage_and_count_mismatch_rejected(generation_request, changes):
    with pytest.raises(GatewayContractViolationError):
        validate_generation_result(generation_request, result_for(generation_request, **changes))


def test_gateway_is_narrow_synchronous_protocol():
    signature = inspect.signature(ImageGenerationGateway.generate)
    assert tuple(signature.parameters) == ("self", "request")
    assert not inspect.iscoroutinefunction(ImageGenerationGateway.generate)


def test_contract_contains_no_domain_mutation_or_provider_secret_fields(generation_request):
    payload = json.dumps(generation_request.model_dump(mode="json"), sort_keys=True)
    for forbidden in (
        "organization_id",
        "raw_message",
        "api_key",
        "proposed_design",
        "revision_update",
        "lock_override",
        "rules_decision",
        "parser_candidate",
    ):
        assert forbidden not in payload


def test_schema_is_valid_and_published_schema_has_no_drift():
    generated = model_gateway_json_schema()
    Draft202012Validator.check_schema(generated)
    assert json.loads((ROOT / "specs/model-gateway/schema.json").read_text()) == generated
