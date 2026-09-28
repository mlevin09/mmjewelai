"""Environment-backed runtime configuration with explicit artifact pins."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from jewelai_assets_gcs import GcsAssetStorageConfig
from jewelai_auth_identity_platform import IdentityPlatformConfig
from jewelai_auth_oidc import OidcJwtConfig
from jewelai_generation_queue_gcp import CloudTasksGenerationConfig

from .generation import GenerationProfile

DEFAULT_ASSET_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
MAX_ASSET_UPLOAD_BYTES = 100 * 1024 * 1024
DEFAULT_HTTP_MULTIPART_OVERHEAD_BYTES = 1024 * 1024
MIN_HTTP_MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_HTTP_REQUEST_BYTES = 110 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactVersions:
    roles: str = "1.0.0"
    dictionary: str = "1.0.0"
    questions: str = "1.0.0"
    rules: str = "1.0.0"
    prompts: str = "1.0.0"


@dataclass(frozen=True)
class RuntimeSettings:
    database_url: str = "sqlite+pysqlite:///./jewelai-v2.db"
    repository_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[4])
    artifacts: ArtifactVersions = field(default_factory=ArtifactVersions)
    oidc: OidcJwtConfig | None = None
    identity_platform: IdentityPlatformConfig | None = None
    auth_provider: str = "oidc"
    asset_signing: GcsAssetStorageConfig | None = None
    asset_upload_max_bytes: int = DEFAULT_ASSET_UPLOAD_MAX_BYTES
    http_max_request_bytes: int = (
        DEFAULT_ASSET_UPLOAD_MAX_BYTES + DEFAULT_HTTP_MULTIPART_OVERHEAD_BYTES
    )
    environment: str = "development"
    gcp_project_id: str | None = None
    generation_tasks: CloudTasksGenerationConfig | None = None
    generation_profiles: tuple[GenerationProfile, ...] = ()
    web_allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.asset_upload_max_bytes, bool) or not isinstance(
            self.asset_upload_max_bytes, int
        ):
            raise ValueError("Asset upload maximum must be an integer")
        if not 1 <= self.asset_upload_max_bytes <= MAX_ASSET_UPLOAD_BYTES:
            raise ValueError("Asset upload maximum must be between 1 and 104857600 bytes")
        if isinstance(self.http_max_request_bytes, bool) or not isinstance(
            self.http_max_request_bytes, int
        ):
            raise ValueError("HTTP request maximum must be an integer")
        if not (
            self.asset_upload_max_bytes + MIN_HTTP_MULTIPART_OVERHEAD_BYTES
            <= self.http_max_request_bytes
            <= MAX_HTTP_REQUEST_BYTES
        ):
            raise ValueError(
                "HTTP request maximum must allow Asset payload plus multipart overhead and "
                f"cannot exceed {MAX_HTTP_REQUEST_BYTES} bytes"
            )
        if (
            not self.environment
            or self.environment != self.environment.strip()
            or len(self.environment) > 32
        ):
            raise ValueError("Environment must be a non-empty exact string up to 32 characters")
        _validate_generation_profiles(self.generation_profiles)
        _validate_web_origins(self.web_allowed_origins)
        if self.auth_provider not in {"oidc", "identity_platform"}:
            raise ValueError("AUTH_PROVIDER must be oidc or identity_platform")

    @classmethod
    def from_environment(
        cls,
        *,
        require_oidc: bool = True,
        require_asset_signer: bool = True,
        require_generation_publisher: bool = False,
    ) -> "RuntimeSettings":
        root = os.getenv("JEWELAI_REPOSITORY_ROOT")
        issuer = os.getenv("OIDC_ISSUER")
        audience = os.getenv("OIDC_AUDIENCE")
        jwks_url = os.getenv("OIDC_JWKS_URL")
        auth_provider = os.getenv("AUTH_PROVIDER", "oidc")
        identity_platform_project = os.getenv("IDENTITY_PLATFORM_PROJECT_ID")
        if auth_provider not in {"oidc", "identity_platform"}:
            raise ValueError("AUTH_PROVIDER must be oidc or identity_platform")
        if require_oidc and auth_provider == "oidc" and not all((issuer, audience, jwks_url)):
            raise ValueError("OIDC_ISSUER, OIDC_AUDIENCE, and OIDC_JWKS_URL are required")
        if require_oidc and auth_provider == "identity_platform" and not identity_platform_project:
            raise ValueError("IDENTITY_PLATFORM_PROJECT_ID is required")
        asset_bucket = os.getenv("GCS_ASSET_BUCKET")
        if require_asset_signer and not asset_bucket:
            raise ValueError("GCS_ASSET_BUCKET is required")
        task_values = (
            os.getenv("CLOUD_TASKS_PROJECT_ID"),
            os.getenv("CLOUD_TASKS_LOCATION"),
            os.getenv("CLOUD_TASKS_QUEUE_ID"),
            os.getenv("GENERATION_WORKER_TASK_URL"),
            os.getenv("GENERATION_TASK_SERVICE_ACCOUNT_EMAIL"),
            os.getenv("GENERATION_TASK_OIDC_AUDIENCE"),
        )
        if require_generation_publisher and not all(task_values):
            raise ValueError("Complete Cloud Tasks generation configuration is required")
        algorithms = tuple(
            item.strip()
            for item in os.getenv("OIDC_ALLOWED_ALGORITHMS", "RS256").split(",")
            if item.strip()
        )
        asset_upload_max_bytes = _strict_bounded_integer(
            os.getenv("ASSET_UPLOAD_MAX_BYTES"),
            default=DEFAULT_ASSET_UPLOAD_MAX_BYTES,
            maximum=MAX_ASSET_UPLOAD_BYTES,
            name="ASSET_UPLOAD_MAX_BYTES",
        )
        http_max_request_bytes = _strict_bounded_integer(
            os.getenv("HTTP_MAX_REQUEST_BYTES"),
            default=asset_upload_max_bytes + DEFAULT_HTTP_MULTIPART_OVERHEAD_BYTES,
            maximum=MAX_HTTP_REQUEST_BYTES,
            name="HTTP_MAX_REQUEST_BYTES",
        )
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            repository_root=Path(root).resolve() if root else Path(__file__).resolve().parents[4],
            artifacts=ArtifactVersions(
                roles=os.getenv("ROLE_ARTIFACT_VERSION", "1.0.0"),
                dictionary=os.getenv("DICTIONARY_ARTIFACT_VERSION", "1.0.0"),
                questions=os.getenv("QUESTION_ARTIFACT_VERSION", "1.0.0"),
                rules=os.getenv("RULES_ARTIFACT_VERSION", "1.0.0"),
                prompts=os.getenv("PROMPT_ARTIFACT_VERSION", "1.0.0"),
            ),
            oidc=(
                OidcJwtConfig(
                    issuer=issuer,
                    audience=audience,
                    jwks_url=jwks_url,
                    allowed_algorithms=algorithms,
                    http_timeout_seconds=float(os.getenv("OIDC_HTTP_TIMEOUT_SECONDS", "5")),
                    jwks_cache_ttl_seconds=int(os.getenv("OIDC_JWKS_CACHE_TTL_SECONDS", "300")),
                    leeway_seconds=int(os.getenv("OIDC_LEEWAY_SECONDS", "30")),
                )
                if all((issuer, audience, jwks_url))
                else None
            ),
            identity_platform=(
                IdentityPlatformConfig(project_id=identity_platform_project)
                if identity_platform_project
                else None
            ),
            auth_provider=auth_provider,
            asset_signing=(
                GcsAssetStorageConfig(
                    bucket_name=asset_bucket,
                    project_id=os.getenv("GCP_PROJECT_ID"),
                    signing_service_account_email=os.getenv("GCS_SIGNING_SERVICE_ACCOUNT_EMAIL"),
                )
                if asset_bucket
                else None
            ),
            asset_upload_max_bytes=asset_upload_max_bytes,
            http_max_request_bytes=http_max_request_bytes,
            environment=os.getenv("JEWELAI_ENVIRONMENT", "development"),
            gcp_project_id=os.getenv("GCP_PROJECT_ID"),
            generation_tasks=(
                CloudTasksGenerationConfig(
                    project_id=task_values[0],
                    location=task_values[1],
                    queue_id=task_values[2],
                    worker_task_url=task_values[3],
                    oidc_service_account_email=task_values[4],
                    oidc_audience=task_values[5],
                    api_timeout_seconds=float(os.getenv("CLOUD_TASKS_API_TIMEOUT_SECONDS", "5")),
                )
                if all(task_values)
                else None
            ),
            generation_profiles=_parse_generation_profiles(os.getenv("GENERATION_PROFILES_JSON")),
            web_allowed_origins=_parse_web_allowed_origins(os.getenv("WEB_ALLOWED_ORIGINS")),
        )


def _strict_bounded_integer(value: str | None, *, default: int, maximum: int, name: str) -> int:
    if value is None:
        return default
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"{name} must be an integer")
    parsed = int(value)
    if not 1 <= parsed <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return parsed


def _parse_generation_profiles(value: str | None) -> tuple[GenerationProfile, ...]:
    if value is None or value == "":
        return ()
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("GENERATION_PROFILES_JSON must be valid JSON") from exc
    if not isinstance(raw, list):
        raise ValueError("GENERATION_PROFILES_JSON must be a JSON array")
    if len(raw) > 20:
        raise ValueError("GENERATION_PROFILES_JSON cannot contain more than 20 profiles")
    profiles = tuple(GenerationProfile.model_validate(item) for item in raw)
    _validate_generation_profiles(profiles)
    return profiles


def _validate_generation_profiles(profiles: tuple[GenerationProfile, ...]) -> None:
    if len(profiles) > 20:
        raise ValueError("Generation profile registry cannot contain more than 20 profiles")
    ids = tuple(profile.profile_id for profile in profiles)
    if len(ids) != len(set(ids)):
        raise ValueError("Generation profile IDs must be unique")


def _parse_web_allowed_origins(value: str | None) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    origins = tuple(value.split(","))
    _validate_web_origins(origins)
    return origins


def _validate_web_origins(origins: tuple[str, ...]) -> None:
    if len(origins) != len(set(origins)):
        raise ValueError("WEB_ALLOWED_ORIGINS must not contain duplicates")
    for origin in origins:
        if (
            not origin
            or origin != origin.strip()
            or any(character.isspace() for character in origin)
        ):
            raise ValueError("WEB_ALLOWED_ORIGINS entries must be exact origins without whitespace")
        if "*" in origin:
            raise ValueError("WEB_ALLOWED_ORIGINS does not permit wildcards")
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or origin != f"{parsed.scheme}://{parsed.netloc}"
        ):
            raise ValueError("WEB_ALLOWED_ORIGINS entries must be exact HTTP(S) origins")
        hostname = parsed.hostname
        if parsed.scheme == "http" and hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Production WEB_ALLOWED_ORIGINS entries must use HTTPS")
