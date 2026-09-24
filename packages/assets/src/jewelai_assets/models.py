"""Immutable Asset v1 contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ASSET_SCHEMA_VERSION = "1.0.0"
ContentHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ObjectKey = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=500,
        pattern=r"^organizations/[0-9a-f-]+/projects/[0-9a-f-]+/assets/[0-9a-f-]+/original\.(png|jpg|webp)$",
    ),
]
ProviderOutputId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$",
    ),
]
SafeErrorDetail = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class AssetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetKind(StrEnum):
    REFERENCE = "reference"
    GENERATED = "generated"


class AssetStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class AssetContentType(StrEnum):
    PNG = "image/png"
    JPEG = "image/jpeg"
    WEBP = "image/webp"


class AssetErrorCode(StrEnum):
    STORAGE_UNAVAILABLE = "storage_unavailable"
    STORAGE_CONFLICT = "storage_conflict"


class AssetIngestionPolicy(AssetModel):
    max_bytes: Annotated[int, Field(ge=1, le=100 * 1024 * 1024)] = 20 * 1024 * 1024


class AssetIngestionRequest(AssetModel):
    asset_id: UUID
    organization_id: UUID
    project_id: UUID
    session_id: UUID
    kind: AssetKind
    declared_content_type: AssetContentType
    generation_run_id: UUID | None = None
    generation_output_ordinal: Annotated[int, Field(ge=1, le=4)] | None = None
    provider_output_id: ProviderOutputId | None = None
    parent_asset_id: UUID | None = None

    @model_validator(mode="after")
    def validate_lineage_shape(self):
        generation_fields = (
            self.generation_run_id,
            self.generation_output_ordinal,
        )
        if self.kind is AssetKind.REFERENCE and any(item is not None for item in generation_fields):
            raise ValueError("Reference assets cannot carry generation lineage")
        if self.kind is AssetKind.REFERENCE and self.provider_output_id is not None:
            raise ValueError("Reference assets cannot carry a provider output ID")
        if self.kind is AssetKind.GENERATED and any(item is None for item in generation_fields):
            raise ValueError("Generated assets require run and output ordinal lineage")
        if self.parent_asset_id == self.asset_id:
            raise ValueError("An asset cannot parent itself")
        return self


class StoredObject(AssetModel):
    object_key: ObjectKey
    content_type: AssetContentType
    content_hash: ContentHash
    byte_size: Annotated[int, Field(gt=0)]


class Asset(AssetModel):
    schema_version: Literal["1.0.0"] = ASSET_SCHEMA_VERSION
    asset_id: UUID
    organization_id: UUID
    project_id: UUID
    session_id: UUID
    kind: AssetKind
    status: AssetStatus
    object_key: ObjectKey
    content_type: AssetContentType
    content_hash: ContentHash
    byte_size: Annotated[int, Field(gt=0)]
    generation_run_id: UUID | None = None
    generation_output_ordinal: Annotated[int, Field(ge=1, le=4)] | None = None
    provider_output_id: ProviderOutputId | None = None
    parent_asset_id: UUID | None = None
    created_at: datetime
    ready_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: AssetErrorCode | None = None
    error_detail: SafeErrorDetail | None = None

    @model_validator(mode="after")
    def validate_lifecycle_and_lineage(self):
        if self.kind is AssetKind.REFERENCE:
            if any(
                item is not None
                for item in (
                    self.generation_run_id,
                    self.generation_output_ordinal,
                    self.provider_output_id,
                )
            ):
                raise ValueError("Reference assets cannot carry generation lineage")
        elif self.generation_run_id is None or self.generation_output_ordinal is None:
            raise ValueError("Generated assets require run and output ordinal lineage")
        if self.parent_asset_id == self.asset_id:
            raise ValueError("An asset cannot parent itself")
        if self.status is AssetStatus.PENDING:
            valid = all(
                item is None
                for item in (self.ready_at, self.failed_at, self.error_code, self.error_detail)
            )
        elif self.status is AssetStatus.READY:
            valid = self.ready_at is not None and all(
                item is None for item in (self.failed_at, self.error_code, self.error_detail)
            )
        else:
            valid = (
                self.failed_at is not None
                and self.ready_at is None
                and self.error_code is not None
                and self.error_detail is not None
            )
        if not valid:
            raise ValueError(f"Asset fields are inconsistent with {self.status} status")
        terminal_at = self.ready_at or self.failed_at
        if terminal_at is not None and terminal_at < self.created_at:
            raise ValueError("Asset terminal timestamp cannot precede creation")
        return self
