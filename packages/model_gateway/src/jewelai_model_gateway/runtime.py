"""Transient binary execution contracts excluded from persisted gateway schemas."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pydantic import TypeAdapter

from .gateway import GatewayContractViolationError, validate_generation_result
from .models import GenerationRequest, GenerationResult, ProviderOutputId

_PROVIDER_OUTPUT_ID = TypeAdapter(ProviderOutputId)


@dataclass(frozen=True)
class RetrievedImageOutput:
    """One transient provider image payload; content is intentionally repr-hidden."""

    ordinal: int
    provider_output_id: ProviderOutputId | None
    declared_content_type: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or not 1 <= self.ordinal <= 4
        ):
            raise ValueError("Retrieved output ordinal must be between 1 and 4")
        if self.declared_content_type != "image/png":
            raise ValueError("Retrieved image output must declare image/png")
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("Retrieved image output content must be non-empty bytes")
        if self.provider_output_id is not None:
            object.__setattr__(
                self,
                "provider_output_id",
                _PROVIDER_OUTPUT_ID.validate_python(self.provider_output_id),
            )


@dataclass(frozen=True)
class GenerationExecution:
    """Metadata result paired with transient, non-persistable provider bytes."""

    result: GenerationResult
    outputs: tuple[RetrievedImageOutput, ...]


@runtime_checkable
class ImageGenerationExecutor(Protocol):
    def execute(self, request: GenerationRequest) -> GenerationExecution:
        """Execute one provider request and return metadata plus transient outputs."""


def validate_generation_execution(
    request: GenerationRequest, execution: GenerationExecution
) -> GenerationExecution:
    """Validate metadata lineage and exact transient-output alignment."""
    request = GenerationRequest.model_validate(request)
    if not isinstance(execution, GenerationExecution):
        raise GatewayContractViolationError
    if not isinstance(execution.outputs, tuple) or any(
        not isinstance(output, RetrievedImageOutput) for output in execution.outputs
    ):
        raise GatewayContractViolationError
    result = validate_generation_result(request, execution.result)
    if len(execution.outputs) != len(result.outputs):
        raise GatewayContractViolationError
    expected = tuple(
        (descriptor.ordinal, descriptor.provider_output_id) for descriptor in result.outputs
    )
    actual = tuple((output.ordinal, output.provider_output_id) for output in execution.outputs)
    if actual != expected:
        raise GatewayContractViolationError
    if any(output.declared_content_type != "image/png" for output in execution.outputs):
        raise GatewayContractViolationError
    return GenerationExecution(result=result, outputs=execution.outputs)
