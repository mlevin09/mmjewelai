"""Immutable provider-neutral Model Gateway v1 contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from jewelai_prompts import CompiledPrompt
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MODEL_GATEWAY_SCHEMA_VERSION = "1.0.0"
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
SafeDetail = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ProviderRequestId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
ProviderOutputId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$",
    ),
]
Version = Annotated[str, StringConstraints(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")]


class GatewayModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GenerationConfiguration(GatewayModel):
    output_count: Annotated[int, Field(ge=1, le=4)] = 1


class GenerationRequest(GatewayModel):
    schema_version: Literal["1.0.0"] = MODEL_GATEWAY_SCHEMA_VERSION
    generation_run_id: UUID
    prompt_revision_id: UUID
    compiled_prompt: CompiledPrompt
    provider: Identifier
    model: Identifier
    configuration: GenerationConfiguration


class GeneratedOutputDescriptor(GatewayModel):
    ordinal: Annotated[int, Field(ge=1, le=4)]
    provider_output_id: ProviderOutputId | None = None
    media_type: Literal["image"] = "image"
    width: Annotated[int, Field(ge=1, le=32768)] | None = None
    height: Annotated[int, Field(ge=1, le=32768)] | None = None

    @model_validator(mode="after")
    def validate_dimensions(self):
        if (self.width is None) != (self.height is None):
            raise ValueError("Provider output width and height must be supplied together")
        return self


class GenerationResult(GatewayModel):
    schema_version: Literal["1.0.0"] = MODEL_GATEWAY_SCHEMA_VERSION
    generation_run_id: UUID
    provider: Identifier
    model: Identifier
    provider_request_id: ProviderRequestId | None = None
    outputs: Annotated[tuple[GeneratedOutputDescriptor, ...], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def validate_outputs(self):
        ordinals = tuple(item.ordinal for item in self.outputs)
        if ordinals != tuple(range(1, len(self.outputs) + 1)):
            raise ValueError("Provider outputs must use unique contiguous ordinals starting at 1")
        ids = [item.provider_output_id for item in self.outputs if item.provider_output_id]
        if len(ids) != len(set(ids)):
            raise ValueError("Provider output IDs must be unique when present")
        return self


class GenerationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationErrorCode(StrEnum):
    GATEWAY_UNAVAILABLE = "gateway_unavailable"
    GATEWAY_TIMEOUT = "gateway_timeout"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_INVALID_RESPONSE = "provider_invalid_response"
    GATEWAY_CONTRACT_VIOLATION = "gateway_contract_violation"


class GenerationRun(GatewayModel):
    generation_run_id: UUID
    session_id: UUID
    prompt_revision_id: UUID
    prompt_content_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    profile_id: Identifier
    profile_version: Version
    provider: Identifier
    model: Identifier
    configuration: GenerationConfiguration
    status: GenerationStatus
    attempt: Annotated[int, Field(ge=1)] = 1
    parent_generation_run_id: UUID | None = None
    result: GenerationResult | None = None
    error_code: GenerationErrorCode | None = None
    error_detail: SafeDetail | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self):
        if self.parent_generation_run_id == self.generation_run_id:
            raise ValueError("A generation run cannot be its own parent")
        if self.status is GenerationStatus.PENDING:
            valid = (
                self.started_at is None
                and self.completed_at is None
                and self.result is None
                and self.error_code is None
                and self.error_detail is None
            )
        elif self.status is GenerationStatus.RUNNING:
            valid = (
                self.started_at is not None
                and self.completed_at is None
                and self.result is None
                and self.error_code is None
                and self.error_detail is None
            )
        elif self.status is GenerationStatus.SUCCEEDED:
            valid = (
                self.started_at is not None
                and self.completed_at is not None
                and self.result is not None
                and self.error_code is None
                and self.error_detail is None
            )
        else:
            valid = (
                self.started_at is not None
                and self.completed_at is not None
                and self.result is None
                and self.error_code is not None
                and self.error_detail is not None
            )
        if not valid:
            raise ValueError(f"Generation run fields are inconsistent with {self.status} status")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("Generation start cannot precede creation")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("Generation completion cannot precede start")
        if self.result is not None:
            if (
                self.result.generation_run_id != self.generation_run_id
                or self.result.provider != self.provider
                or self.result.model != self.model
                or len(self.result.outputs) != self.configuration.output_count
            ):
                raise ValueError("Generation result lineage or output count does not match its run")
        return self
