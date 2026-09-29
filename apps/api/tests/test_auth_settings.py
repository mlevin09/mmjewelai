import pytest
from jewelai_assets_gcs import GcsAssetStorageConfig
from jewelai_auth_identity_platform import IdentityPlatformConfig
from jewelai_auth_oidc import OidcJwtConfig
from jewelai_persistence import DatabasePoolConfig
from jewelai_text_understanding_google import GoogleTextUnderstandingConfig
from pydantic import ValidationError

from jewelai_api.settings import RuntimeSettings


def test_database_pool_configuration_is_bounded_and_exact(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "4")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "900")
    assert DatabasePoolConfig.from_environment() == DatabasePoolConfig(
        pool_size=4,
        max_overflow=1,
        pool_timeout_seconds=20,
        pool_recycle_seconds=900,
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [("DB_POOL_SIZE", "0"), ("DB_MAX_OVERFLOW", "-1"), ("DB_POOL_TIMEOUT_SECONDS", " 5")],
)
def test_database_pool_configuration_rejects_invalid_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        DatabasePoolConfig.from_environment()


def test_runtime_settings_load_valid_oidc_environment(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.test")
    monkeypatch.setenv("OIDC_AUDIENCE", "jewelai-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://issuer.test/keys")
    settings = RuntimeSettings.from_environment(require_asset_signer=False)
    assert settings.oidc == OidcJwtConfig(
        issuer="https://issuer.test",
        audience="jewelai-api",
        jwks_url="https://issuer.test/keys",
    )


def test_runtime_settings_load_identity_platform_environment(monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "identity_platform")
    monkeypatch.setenv("IDENTITY_PLATFORM_PROJECT_ID", "mmjewellai-preprod")
    settings = RuntimeSettings.from_environment(require_asset_signer=False)
    assert settings.auth_provider == "identity_platform"
    assert settings.identity_platform == IdentityPlatformConfig(project_id="mmjewellai-preprod")
    assert settings.oidc is None


def test_runtime_settings_load_exact_optional_text_understanding_model(monkeypatch):
    monkeypatch.setenv("TEXT_UNDERSTANDING_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_TEXT_UNDERSTANDING_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GOOGLE_TEXT_UNDERSTANDING_TIMEOUT_SECONDS", "25")
    settings = RuntimeSettings.from_environment(
        require_oidc=False,
        require_asset_signer=False,
    )
    assert settings.text_understanding == GoogleTextUnderstandingConfig(
        model="gemini-3.1-flash-lite",
        timeout_seconds=25,
    )


def test_runtime_settings_reject_normalized_text_understanding_model(monkeypatch):
    monkeypatch.setenv("TEXT_UNDERSTANDING_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_TEXT_UNDERSTANDING_MODEL", " gemini-3.1-flash-lite")
    with pytest.raises(ValueError, match="exact bounded model ID"):
        RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)


@pytest.mark.parametrize(
    ("provider", "model"),
    [("google", None), (None, "gemini-3.1-flash-lite"), ("openai", "model")],
)
def test_runtime_settings_reject_incomplete_or_unknown_text_provider(monkeypatch, provider, model):
    for name, value in (
        ("TEXT_UNDERSTANDING_PROVIDER", provider),
        ("GOOGLE_TEXT_UNDERSTANDING_MODEL", model),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="TEXT_UNDERSTANDING_PROVIDER"):
        RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)


def test_runtime_settings_require_identity_platform_project(monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "identity_platform")
    monkeypatch.delenv("IDENTITY_PLATFORM_PROJECT_ID", raising=False)
    with pytest.raises(ValueError, match="IDENTITY_PLATFORM_PROJECT_ID is required"):
        RuntimeSettings.from_environment(require_asset_signer=False)


@pytest.mark.parametrize("missing", ["OIDC_ISSUER", "OIDC_AUDIENCE", "OIDC_JWKS_URL"])
def test_runtime_settings_require_complete_oidc_environment(monkeypatch, missing):
    values = {
        "OIDC_ISSUER": "https://issuer.test",
        "OIDC_AUDIENCE": "jewelai-api",
        "OIDC_JWKS_URL": "https://issuer.test/keys",
    }
    values.pop(missing)
    for name in ("OIDC_ISSUER", "OIDC_AUDIENCE", "OIDC_JWKS_URL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="required"):
        RuntimeSettings.from_environment(require_asset_signer=False)


def test_runtime_settings_reject_insecure_jwks(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.test")
    monkeypatch.setenv("OIDC_AUDIENCE", "jewelai-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "http://issuer.test/keys")
    with pytest.raises(ValidationError, match="HTTPS"):
        RuntimeSettings.from_environment(require_asset_signer=False)


def test_runtime_settings_load_valid_gcs_asset_signing_environment(monkeypatch):
    monkeypatch.setenv("GCS_ASSET_BUCKET", "jewelai-assets-prod")
    monkeypatch.setenv("GCP_PROJECT_ID", "jewelai-prod")
    monkeypatch.setenv(
        "GCS_SIGNING_SERVICE_ACCOUNT_EMAIL",
        "signer@jewelai-prod.iam.gserviceaccount.com",
    )
    settings = RuntimeSettings.from_environment(require_oidc=False)
    assert settings.asset_signing == GcsAssetStorageConfig(
        bucket_name="jewelai-assets-prod",
        project_id="jewelai-prod",
        signing_service_account_email="signer@jewelai-prod.iam.gserviceaccount.com",
    )


def test_runtime_settings_require_gcs_bucket_for_production_signer(monkeypatch):
    monkeypatch.delenv("GCS_ASSET_BUCKET", raising=False)
    with pytest.raises(ValueError, match="GCS_ASSET_BUCKET"):
        RuntimeSettings.from_environment(require_oidc=False)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GCS_ASSET_BUCKET", "Invalid Bucket"),
        ("GCP_PROJECT_ID", "BAD"),
        ("GCS_SIGNING_SERVICE_ACCOUNT_EMAIL", "not-an-account"),
    ],
)
def test_runtime_settings_delegate_invalid_gcs_values_to_adapter_config(monkeypatch, name, value):
    monkeypatch.setenv("GCS_ASSET_BUCKET", "jewelai-assets-prod")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        RuntimeSettings.from_environment(require_oidc=False)


def test_runtime_settings_do_not_require_gcs_when_signer_is_injected(monkeypatch):
    monkeypatch.delenv("GCS_ASSET_BUCKET", raising=False)
    settings = RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)
    assert settings.asset_signing is None


def test_runtime_settings_load_asset_upload_limit(monkeypatch):
    monkeypatch.setenv("ASSET_UPLOAD_MAX_BYTES", "20971520")
    settings = RuntimeSettings.from_environment(
        require_oidc=False,
        require_asset_signer=False,
    )
    assert settings.asset_upload_max_bytes == 20 * 1024 * 1024
    assert settings.http_max_request_bytes == 21 * 1024 * 1024


def test_runtime_settings_load_separate_raw_http_limit(monkeypatch):
    monkeypatch.setenv("ASSET_UPLOAD_MAX_BYTES", "1024")
    monkeypatch.setenv("HTTP_MAX_REQUEST_BYTES", "66560")
    settings = RuntimeSettings.from_environment(
        require_oidc=False,
        require_asset_signer=False,
    )
    assert settings.asset_upload_max_bytes == 1024
    assert settings.http_max_request_bytes == 66560


@pytest.mark.parametrize("value", ["0", "1024", "not-an-integer", " 66560"])
def test_runtime_settings_reject_invalid_raw_http_limit(monkeypatch, value):
    monkeypatch.setenv("ASSET_UPLOAD_MAX_BYTES", "1024")
    monkeypatch.setenv("HTTP_MAX_REQUEST_BYTES", value)
    with pytest.raises(ValueError, match="HTTP_MAX_REQUEST_BYTES|HTTP request maximum"):
        RuntimeSettings.from_environment(
            require_oidc=False,
            require_asset_signer=False,
        )


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "104857601", "not-an-integer", "true", " 16", "16 "],
)
def test_runtime_settings_reject_invalid_asset_upload_limit(monkeypatch, value):
    monkeypatch.setenv("ASSET_UPLOAD_MAX_BYTES", value)
    with pytest.raises(ValueError, match="ASSET_UPLOAD_MAX_BYTES"):
        RuntimeSettings.from_environment(
            require_oidc=False,
            require_asset_signer=False,
        )


def test_runtime_settings_load_cloud_tasks_and_fail_closed_when_required(monkeypatch):
    names = {
        "CLOUD_TASKS_PROJECT_ID": "jewelai-prod",
        "CLOUD_TASKS_LOCATION": "us-central1",
        "CLOUD_TASKS_QUEUE_ID": "generation",
        "GENERATION_WORKER_TASK_URL": ("https://worker.test/internal/generation-tasks/execute"),
        "GENERATION_TASK_SERVICE_ACCOUNT_EMAIL": ("tasker@jewelai-prod.iam.gserviceaccount.com"),
        "GENERATION_TASK_OIDC_AUDIENCE": "https://worker.test",
    }
    for key in names:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="Cloud Tasks"):
        RuntimeSettings.from_environment(
            require_oidc=False,
            require_asset_signer=False,
            require_generation_publisher=True,
        )
    for key, value in names.items():
        monkeypatch.setenv(key, value)
    settings = RuntimeSettings.from_environment(
        require_oidc=False,
        require_asset_signer=False,
        require_generation_publisher=True,
    )
    assert settings.generation_tasks.queue_id == "generation"


def test_web_origins_and_generation_profiles_are_strict(monkeypatch):
    monkeypatch.setenv("WEB_ALLOWED_ORIGINS", "https://app.example.test,http://localhost:5173")
    monkeypatch.setenv(
        "GENERATION_PROFILES_JSON",
        '[{"profile_id":"default","profile_version":"1.0.0",'
        '"provider":"openai","model":"gpt-image-1",'
        '"configuration":{"output_count":2}}]',
    )
    settings = RuntimeSettings.from_environment(
        require_oidc=False,
        require_asset_signer=False,
    )
    assert settings.web_allowed_origins == (
        "https://app.example.test",
        "http://localhost:5173",
    )
    assert settings.generation_profiles[0].profile_id == "default"
    assert settings.generation_profiles[0].configuration.output_count == 2


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        " http://localhost:5173",
        "https://user@app.example.test",
        "https://app.example.test/path",
        "https://app.example.test?query=1",
        "https://app.example.test#fragment",
        "http://app.example.test",
    ],
)
def test_web_origin_rejects_non_origin_or_insecure_production_values(monkeypatch, origin):
    monkeypatch.setenv("WEB_ALLOWED_ORIGINS", origin)
    with pytest.raises(ValueError):
        RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)


def test_generation_profiles_reject_credentials_and_duplicates(monkeypatch):
    monkeypatch.setenv(
        "GENERATION_PROFILES_JSON",
        '[{"profile_id":"default","profile_version":"1.0.0",'
        '"provider":"openai","model":"gpt-image-1",'
        '"configuration":{"output_count":1},"api_key":"secret"}]',
    )
    with pytest.raises(ValueError):
        RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)

    item = (
        '{"profile_id":"default","profile_version":"1.0.0",'
        '"provider":"openai","model":"gpt-image-1",'
        '"configuration":{"output_count":1}}'
    )
    monkeypatch.setenv("GENERATION_PROFILES_JSON", f"[{item},{item}]")
    with pytest.raises(ValueError, match="unique"):
        RuntimeSettings.from_environment(require_oidc=False, require_asset_signer=False)
