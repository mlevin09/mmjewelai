"""Handled API failures are logged by exception identity, never by message."""

import io
import json
import logging

import pytest
import requests
from conftest import create_hierarchy
from test_stt_proxy import speech_transport, submit

__all__ = ["speech_transport"]  # Shared fake STT transport fixture.


@pytest.fixture
def api_log():
    from jewelai_api.middleware import JsonLogFormatter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger = logging.getLogger("jewelai.api")
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)


def _stt_failures(stream):
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    return [event for event in events if event.get("event") == "stt_request_failed"]


def test_transcription_failure_is_logged_by_type_and_location_only(
    client, speech_transport, monkeypatch, api_log
):
    def failed(*args):
        raise RuntimeError("private-credential-details")

    monkeypatch.setattr("google.oauth2.id_token.fetch_id_token", failed)
    org, _, session = create_hierarchy(client)
    sid = session.json()["session_id"]
    response = submit(client, sid, org)

    assert response.status_code == 503
    [event] = _stt_failures(api_log)
    assert event["severity"] == "ERROR"
    assert event["error_code"] == "stt_unavailable"
    assert event["session_id"] == sid
    assert event["error_type"] == "builtins.RuntimeError"
    assert event["error_origin"][-1].endswith(":failed")
    assert "private" not in api_log.getvalue()
    assert "synthetic-private-token" not in api_log.getvalue()


def test_transcription_timeout_and_invalid_response_are_logged(client, speech_transport, api_log):
    _, _, behavior = speech_transport
    org, _, session = create_hierarchy(client)
    sid = session.json()["session_id"]

    behavior["error"] = requests.Timeout("private-provider-body")
    assert submit(client, sid, org).status_code == 504
    behavior["error"] = None
    behavior["body"] = b"private-provider-body-not-json"
    assert submit(client, sid, org).status_code == 503

    timeout, invalid = _stt_failures(api_log)
    assert timeout["error_code"] == "stt_timeout"
    assert timeout["error_type"] == "requests.exceptions.Timeout"
    assert invalid["error_code"] == "stt_unavailable"
    assert invalid["error_type"] == "json.decoder.JSONDecodeError"
    assert "private-provider-body" not in api_log.getvalue()


def test_successful_transcription_logs_no_failure(client, speech_transport, api_log):
    org, _, session = create_hierarchy(client)
    assert submit(client, session.json()["session_id"], org).status_code == 200
    assert _stt_failures(api_log) == []


def test_asset_ingestion_logger_uses_the_api_json_handler(client):
    from jewelai_api.middleware import JsonLogFormatter

    logger = logging.getLogger("jewelai.assets")
    assert logger.propagate is False
    assert any(isinstance(h.formatter, JsonLogFormatter) for h in logger.handlers)
