import pytest
from jewelai_assets_gcs import GcsAssetStorageConfig
from jewelai_auth_oidc import OidcJwtConfig
from pydantic import ValidationError

from jewelai_api.settings import RuntimeSettings


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
