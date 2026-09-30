"""Transient binary execution contracts excluded from persisted gateway schemas."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import TypeAdapter

from .gateway import GatewayContractViolationError, validate_generation_result
from .models import GenerationRequest, GenerationResult, ProviderOutputId

_PROVIDER_OUTPUT_ID = TypeAdapter(ProviderOutputId)
_SUPPORTED_IMAGE_CONTENT_TYPES = frozenset(("image/png", "image/jpeg", "image/webp"))


@dataclass(frozen=True)
class ImageGenerationEditInput:
    """Transient source-image context for one image-conditioned edit."""

    source_asset_id: UUID
    declared_content_type: str
    content_hash: str
    change_request: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if self.declared_content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
            raise ValueError("Edit input must use a supported image content type")
        if (
            not isinstance(self.content_hash, str)
            or len(self.content_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.content_hash)
        ):
            raise ValueError("Edit input requires a SHA-256 content hash")
        if not isinstance(self.change_request, str) or not self.change_request.strip():
            raise ValueError("Edit input requires an exact change request")
        if self.change_request != self.change_request.strip() or len(self.change_request) > 4000:
            raise ValueError("Edit change request is invalid")
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("Edit input content must be non-empty bytes")


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
        if self.declared_content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
            raise ValueError("Retrieved image output must declare a supported image content type")
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
    def execute(
        self,
        request: GenerationRequest,
        *,
        edit_input: ImageGenerationEditInput | None = None,
    ) -> GenerationExecution:
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
    if any(
        output.declared_content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES
        for output in execution.outputs
    ):
        raise GatewayContractViolationError
    return GenerationExecution(result=result, outputs=execution.outputs)
