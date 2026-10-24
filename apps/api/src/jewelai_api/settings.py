"""Environment-backed runtime configuration with explicit artifact pins."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from jewelai_assets_gcs import GcsAssetStorageConfig
from jewelai_auth_identity_platform import IdentityPlatformConfig
from jewelai_auth_oidc import OidcJwtConfig
from jewelai_domain import (
    KNOWLEDGE_RELEASE_QUALIFICATION_VERSION,
    KnowledgeReleaseCandidateKind,
    KnowledgeReleaseCandidateSelection,
)
from jewelai_generation_queue_gcp import CloudTasksGenerationConfig
from jewelai_text_understanding_google import GoogleTextUnderstandingConfig

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
    knowledge_base: str = "1.0.0"


@dataclass(frozen=True)
class PromptEnrichmentRuntimeConfig:
    """Exact, explicitly enabled release selection for controlled composition."""

    artifact_root: Path
    candidate: KnowledgeReleaseCandidateSelection
    active_release_path: Path
    validation_report_path: Path
    qualification_contract_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, KnowledgeReleaseCandidateSelection):
            raise ValueError("Prompt Enrichment candidate selection must be typed and complete")
        if not all(
            isinstance(path, Path)
            for path in (
                self.artifact_root,
                self.active_release_path,
                self.validation_report_path,
            )
        ):
            raise ValueError("Prompt Enrichment artifact and evidence locations must be paths")
        if self.qualification_contract_version != KNOWLEDGE_RELEASE_QUALIFICATION_VERSION:
            raise ValueError("PROMPT_ENRICHMENT_QUALIFICATION_CONTRACT_VERSION is unsupported")


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
    text_understanding: GoogleTextUnderstandingConfig | None = None
    prompt_enrichment: PromptEnrichmentRuntimeConfig | None = None

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
        if (
            self.environment == "production"
            and self.prompt_enrichment is not None
            and self.prompt_enrichment.candidate.kind
            != KnowledgeReleaseCandidateKind.PRODUCTION_INTENDED
        ):
            raise ValueError(
                "Production Prompt Enrichment composition requires a PRODUCTION_INTENDED candidate"
            )

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
        text_understanding_provider = os.getenv("TEXT_UNDERSTANDING_PROVIDER")
        text_understanding_model = os.getenv("GOOGLE_TEXT_UNDERSTANDING_MODEL")
        if (text_understanding_provider is None) != (text_understanding_model is None):
            raise ValueError(
                "TEXT_UNDERSTANDING_PROVIDER and GOOGLE_TEXT_UNDERSTANDING_MODEL "
                "must be configured together"
            )
        if text_understanding_provider not in {None, "google"}:
            raise ValueError("TEXT_UNDERSTANDING_PROVIDER must be google when configured")
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            repository_root=Path(root).resolve() if root else Path(__file__).resolve().parents[4],
            artifacts=ArtifactVersions(
                roles=os.getenv("ROLE_ARTIFACT_VERSION", "1.0.0"),
                dictionary=os.getenv("DICTIONARY_ARTIFACT_VERSION", "1.0.0"),
                questions=os.getenv("QUESTION_ARTIFACT_VERSION", "1.0.0"),
                rules=os.getenv("RULES_ARTIFACT_VERSION", "1.0.0"),
                prompts=os.getenv("PROMPT_ARTIFACT_VERSION", "1.0.0"),
                knowledge_base=os.getenv("KNOWLEDGE_BASE_ARTIFACT_VERSION", "1.0.0"),
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
            text_understanding=(
                GoogleTextUnderstandingConfig(
                    model=os.environ["GOOGLE_TEXT_UNDERSTANDING_MODEL"],
                    timeout_seconds=float(
                        os.getenv("GOOGLE_TEXT_UNDERSTANDING_TIMEOUT_SECONDS", "30")
                    ),
                )
                if text_understanding_model
                else None
            ),
            prompt_enrichment=_parse_prompt_enrichment_config(),
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


def _parse_prompt_enrichment_config() -> PromptEnrichmentRuntimeConfig | None:
    enabled = os.getenv("PROMPT_ENRICHMENT_ENABLED")
    if enabled in {None, "false"}:
        return None
    if enabled != "true":
        raise ValueError("PROMPT_ENRICHMENT_ENABLED must be exactly true or false")

    names = (
        "PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_ROOT",
        "PROMPT_ENRICHMENT_KNOWLEDGE_PACKAGE_ID",
        "PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_VERSION",
        "PROMPT_ENRICHMENT_ACTIVE_RELEASE_PATH",
        "PROMPT_ENRICHMENT_VALIDATION_REPORT_PATH",
        "PROMPT_ENRICHMENT_QUALIFICATION_CONTRACT_VERSION",
        "PROMPT_ENRICHMENT_CANDIDATE_KIND",
    )
    values = {name: os.getenv(name) for name in names}
    if any(value is None or value == "" for value in values.values()):
        raise ValueError("Enabled Prompt Enrichment requires complete exact release configuration")
    if any(value != value.strip() for value in values.values()):
        raise ValueError(
            "Prompt Enrichment release configuration must not contain outer whitespace"
        )

    try:
        candidate = KnowledgeReleaseCandidateSelection(
            package_id=values["PROMPT_ENRICHMENT_KNOWLEDGE_PACKAGE_ID"],
            artifact_version=values["PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_VERSION"],
            kind=values["PROMPT_ENRICHMENT_CANDIDATE_KIND"],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Prompt Enrichment release selection is invalid") from exc
    return PromptEnrichmentRuntimeConfig(
        artifact_root=Path(values["PROMPT_ENRICHMENT_KNOWLEDGE_ARTIFACT_ROOT"]),
        candidate=candidate,
        active_release_path=Path(values["PROMPT_ENRICHMENT_ACTIVE_RELEASE_PATH"]),
        validation_report_path=Path(values["PROMPT_ENRICHMENT_VALIDATION_REPORT_PATH"]),
        qualification_contract_version=values["PROMPT_ENRICHMENT_QUALIFICATION_CONTRACT_VERSION"],
    )


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
