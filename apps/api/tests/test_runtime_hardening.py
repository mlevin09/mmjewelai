import io
import json
import logging
from pathlib import Path

from conftest import (
    FakeAssetAccessSigner,
    FakeGenerationTaskPublisher,
    FakePrivateObjectStore,
    FakeTokenVerifier,
)
from fastapi.testclient import TestClient

from jewelai_api import create_app
from jewelai_api.middleware import JsonLogFormatter
from jewelai_api.settings import RuntimeSettings

ROOT = Path(__file__).resolve().parents[3]


def hardened_client(engine, *, raw_limit=65_537, raise_server_exceptions=True):
    app = create_app(
        RuntimeSettings(
            database_url="sqlite+pysqlite://",
            repository_root=ROOT,
            asset_upload_max_bytes=1,
            http_max_request_bytes=raw_limit,
            environment="test",
            gcp_project_id="test-project",
        ),
        engine=engine,
        token_verifier=FakeTokenVerifier(),
        asset_access_signer=FakeAssetAccessSigner(),
        asset_object_store=FakePrivateObjectStore(),
        generation_task_publisher=FakeGenerationTaskPublisher(),
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_declared_oversized_body_is_rejected_before_route_parsing(engine):
    with hardened_client(engine) as client:
        response = client.post(
            "/organizations",
            headers={
                "Authorization": "Bearer secret-token-never-log",
                "Content-Type": "application/json",
                "Content-Length": "70000",
            },
            content=b"{}",
        )
    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"
    assert response.headers["x-request-id"]


def test_streaming_body_without_content_length_is_bounded(engine):
    def chunks():
        yield b"x" * 40_000
        yield b"y" * 40_000

    with hardened_client(engine) as client:
        response = client.post(
            "/organizations",
            headers={
                "Authorization": "Bearer test-stream",
                "Content-Type": "application/json",
            },
            content=chunks(),
        )
    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"


def test_small_json_request_still_works_and_has_safe_headers(engine):
    with hardened_client(engine) as client:
        response = client.post(
            "/organizations",
            headers={"Authorization": "Bearer test-safe"},
            json={"name": "Safe organization"},
        )
    assert response.status_code == 201
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_request_log_is_structured_and_redacts_headers_and_body(engine):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("jewelai.api")
    logger.addHandler(handler)
    try:
        with hardened_client(engine) as client:
            response = client.post(
                "/organizations",
                headers={
                    "Authorization": "Bearer test-secret-token-never-log",
                    "X-Cloud-Trace-Context": "0123456789abcdef0123456789abcdef/1;o=1",
                },
                json={"name": "private-body-never-log"},
            )
    finally:
        logger.removeHandler(handler)
    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["severity"] == "INFO"
    assert payload["event"] == "http_request_completed"
    assert payload["request_id"] == response.headers["x-request-id"]
    assert payload["route"] == "/organizations"
    assert payload["status"] == 201
    assert payload["logging.googleapis.com/trace"].endswith("/0123456789abcdef0123456789abcdef")
    serialized = json.dumps(payload)
    assert "test-secret-token-never-log" not in serialized
    assert "private-body-never-log" not in serialized


def test_unhandled_error_is_redacted_from_response_and_logs(engine):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("jewelai.api")
    logger.addHandler(handler)
    try:
        with hardened_client(engine, raise_server_exceptions=False) as client:

            def unsafe_failure():
                raise RuntimeError("provider raw secret signed URL prompt bytes")

            client.app.add_api_route("/test-unhandled", unsafe_failure, methods=["GET"])
            response = client.get("/test-unhandled")
    finally:
        logger.removeHandler(handler)
    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "detail": "Internal server error",
    }
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert any(event.get("event") == "application_error" for event in events)
    serialized = json.dumps(events)
    assert "provider raw secret" not in serialized
    assert "signed URL" not in serialized
    assert "prompt bytes" not in serialized
