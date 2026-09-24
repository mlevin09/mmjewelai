from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jewelai_persistence import Base, create_database_engine

from jewelai_api import create_app
from jewelai_api.settings import RuntimeSettings

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


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
def app(engine):
    return create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
        ),
        engine=engine,
        clock=lambda: NOW,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as value:
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
