from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jewelai_assets import AssetAccessUnavailableError
from jewelai_auth import AuthenticationError, VerifiedIdentity
from jewelai_model_gateway import GenerationConfiguration
from jewelai_persistence import Base, create_database_engine

from jewelai_api import create_app
from jewelai_api.generation import GenerationProfile, GenerationProfileRegistry
from jewelai_api.settings import RuntimeSettings

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class FakeTokenVerifier:
    def verify(self, token: str) -> VerifiedIdentity:
        if not token.startswith("test-"):
            raise AuthenticationError("Bearer token is invalid")
        subject = token.removeprefix("test-")
        return VerifiedIdentity(
            issuer="https://issuer.test",
            subject=subject,
            email=f"{subject}@example.test",
            display_name=subject.replace("-", " ").title(),
        )


class FakeAssetAccessSigner:
    def __init__(self):
        self.calls = []
        self.url = "https://assets.example.test/signed?test-capability=1"
        self.error = None

    def sign_read(self, object_key, expires_at):
        self.calls.append((object_key, expires_at))
        if self.error is not None:
            raise AssetAccessUnavailableError(self.error)
        return self.url


@pytest.fixture
def engine(tmp_path):
    database = tmp_path / "runtime.db"
    value = create_database_engine(
        f"sqlite+pysqlite:///{database}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(value)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def asset_access_signer():
    return FakeAssetAccessSigner()


@pytest.fixture
def app(engine, asset_access_signer):
    return create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
        ),
        engine=engine,
        clock=lambda: NOW,
        generation_profiles=GenerationProfileRegistry(
            (
                GenerationProfile(
                    profile_id="test_default",
                    profile_version="1.0.0",
                    provider="test",
                    model="deterministic-image-v1",
                    configuration=GenerationConfiguration(output_count=1),
                ),
            )
        ),
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=asset_access_signer,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as value:
        value.headers["Authorization"] = "Bearer test-owner-a"
        yield value


def create_hierarchy(client, *, role_id="retail_client", locale="en"):
    organization = client.post("/organizations", json={"name": "Organization A"})
    assert organization.status_code == 201
    organization_id = organization.json()["organization_id"]
    project = client.post(f"/organizations/{organization_id}/projects", json={"name": "Project A"})
    assert project.status_code == 201
    project_id = project.json()["project_id"]
    session = client.post(
        f"/projects/{project_id}/sessions",
        headers={"X-Organization-ID": organization_id},
        json={"role_id": role_id, "locale": locale},
    )
    return organization_id, project_id, session
