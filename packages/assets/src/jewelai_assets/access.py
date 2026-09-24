"""Provider-neutral, short-lived private Asset read access."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .ingestion import validate_asset_object_key
from .models import Asset, AssetContentType, AssetStatus, ObjectKey

ASSET_ACCESS_SCHEMA_VERSION = "1.0.0"
HttpsSignedUrl = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=8192,
        pattern=r"^https://[^\s]+$",
    ),
]


class AssetAccessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetAccessPolicy(AssetAccessModel):
    default_ttl_seconds: Annotated[int, Field(ge=1, le=900)] = 300
    max_ttl_seconds: Annotated[int, Field(ge=1, le=900)] = 900

    @model_validator(mode="after")
    def validate_ttl_order(self):
        if self.default_ttl_seconds > self.max_ttl_seconds:
            raise ValueError("Default asset access TTL cannot exceed the maximum TTL")
        return self


class SignedAssetReadAccess(AssetAccessModel):
    schema_version: Literal["1.0.0"] = ASSET_ACCESS_SCHEMA_VERSION
    asset_id: UUID
    method: Literal["GET"] = "GET"
    url: HttpsSignedUrl
    expires_at: datetime
    content_type: AssetContentType | None = None

    @model_validator(mode="after")
    def validate_url_and_timezone(self):
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Asset access URL must be an absolute HTTPS URL")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Asset access expiration must be timezone-aware")
        return self


class AssetAccessError(RuntimeError):
    """Safe base error for temporary Asset read-access failures."""


class AssetNotReadyError(AssetAccessError):
    pass


class AssetAccessUnavailableError(AssetAccessError):
    pass


class AssetAccessContractError(AssetAccessError):
    pass


class PrivateObjectAccessSigner(Protocol):
    def sign_read(self, object_key: ObjectKey, expires_at: datetime) -> str: ...


def issue_asset_read_access(
    asset: Asset,
    signer: PrivateObjectAccessSigner,
    *,
    requested_ttl_seconds: int | None = None,
    policy: AssetAccessPolicy | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SignedAssetReadAccess:
    try:
        asset = Asset.model_validate(asset)
        policy = AssetAccessPolicy.model_validate(policy or {})
    except ValidationError as exc:
        raise AssetAccessContractError("Asset access input is invalid") from exc
    if asset.status is not AssetStatus.READY:
        raise AssetNotReadyError("Only ready assets can receive temporary read access")
    try:
        validate_asset_object_key(asset)
    except ValueError as exc:
        raise AssetAccessContractError("Asset object key is not canonical") from exc

    if requested_ttl_seconds is None:
        ttl_seconds = policy.default_ttl_seconds
    elif isinstance(requested_ttl_seconds, bool) or not isinstance(requested_ttl_seconds, int):
        raise AssetAccessContractError("Asset access TTL must be an integer number of seconds")
    else:
        ttl_seconds = requested_ttl_seconds
    if ttl_seconds <= 0 or ttl_seconds > policy.max_ttl_seconds:
        raise AssetAccessContractError("Requested asset access TTL is outside the allowed range")

    issued_at = (clock or (lambda: datetime.now(UTC)))()
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise AssetAccessContractError("Asset access clock must return a timezone-aware timestamp")
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    try:
        url = signer.sign_read(asset.object_key, expires_at)
    except AssetAccessError:
        raise
    except Exception as exc:
        raise AssetAccessUnavailableError("Private asset read access is unavailable") from exc
    try:
        return SignedAssetReadAccess(
            asset_id=asset.asset_id,
            url=url,
            expires_at=expires_at,
            content_type=asset.content_type,
        )
    except ValidationError as exc:
        raise AssetAccessContractError("Asset signer returned invalid read access") from exc
