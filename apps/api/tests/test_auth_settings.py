import pytest
from jewelai_auth_oidc import OidcJwtConfig
from pydantic import ValidationError

from jewelai_api.settings import RuntimeSettings


def test_runtime_settings_load_valid_oidc_environment(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.test")
    monkeypatch.setenv("OIDC_AUDIENCE", "jewelai-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://issuer.test/keys")
    settings = RuntimeSettings.from_environment()
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
        RuntimeSettings.from_environment()


def test_runtime_settings_reject_insecure_jwks(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.test")
    monkeypatch.setenv("OIDC_AUDIENCE", "jewelai-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "http://issuer.test/keys")
    with pytest.raises(ValidationError, match="HTTPS"):
        RuntimeSettings.from_environment()
