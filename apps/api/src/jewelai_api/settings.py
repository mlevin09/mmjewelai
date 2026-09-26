"""Environment-backed runtime configuration with explicit artifact pins."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from jewelai_assets_gcs import GcsAssetStorageConfig
from jewelai_auth_oidc import OidcJwtConfig
from jewelai_generation_queue_gcp import CloudTasksGenerationConfig


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
    asset_signing: GcsAssetStorageConfig | None = None
    generation_tasks: CloudTasksGenerationConfig | None = None

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
        if require_oidc and not all((issuer, audience, jwks_url)):
            raise ValueError("OIDC_ISSUER, OIDC_AUDIENCE, and OIDC_JWKS_URL are required")
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
            asset_signing=(
                GcsAssetStorageConfig(
                    bucket_name=asset_bucket,
                    project_id=os.getenv("GCP_PROJECT_ID"),
                    signing_service_account_email=os.getenv("GCS_SIGNING_SERVICE_ACCOUNT_EMAIL"),
                )
                if asset_bucket
                else None
            ),
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
        )
