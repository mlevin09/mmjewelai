"""Narrow injectable gateway protocol, errors, and untrusted-result validation."""

from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from .models import GenerationRequest, GenerationResult


class GatewayError(RuntimeError):
    code = "gateway_unavailable"
    safe_detail = "The generation gateway is unavailable"


class GatewayUnavailableError(GatewayError):
    pass


class GatewayTimeoutError(GatewayError):
    code = "gateway_timeout"
    safe_detail = "The generation gateway timed out"


class ProviderRejectedError(GatewayError):
    code = "provider_rejected"
    safe_detail = "The provider rejected the generation request"


class InvalidProviderResponseError(GatewayError):
    code = "provider_invalid_response"
    safe_detail = "The provider returned an invalid response"


class GatewayContractViolationError(GatewayError):
    code = "gateway_contract_violation"
    safe_detail = "The provider result violated the Model Gateway contract"


@runtime_checkable
class ImageGenerationGateway(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate provider output metadata from one validated immutable prompt."""


def validate_generation_result(request: GenerationRequest, result) -> GenerationResult:
    request = GenerationRequest.model_validate(request)
    try:
        result = GenerationResult.model_validate(result)
    except ValidationError as exc:
        raise GatewayContractViolationError from exc
    if (
        result.generation_run_id != request.generation_run_id
        or result.provider != request.provider
        or result.model != request.model
        or len(result.outputs) != request.configuration.output_count
    ):
        raise GatewayContractViolationError
    return result
