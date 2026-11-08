"""Bounded fake-transport tests; no Google credential or speech inference calls."""

import json
from uuid import uuid4

import pytest
import requests
from conftest import create_hierarchy
from sqlalchemy import text

SERVICE = "https://jewelai-preprod-stt-example-ew.a.run.app"
RESULT = {"schema_version": "1.0.0", "status": "transcribed", "text": "Хочу кольцо."}


@pytest.fixture
def speech_transport(monkeypatch):
    calls = []
    tokens = []
    behavior = {"status": 200, "body": json.dumps(RESULT).encode(), "error": None}

    def token(request, audience):
        tokens.append(audience)
        return "synthetic-private-token"

    class Reply:
        def __enter__(self):
            self.status_code = behavior["status"]
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, chunk_size):
            body = behavior["body"]
            for start in range(0, len(body), chunk_size):
                yield body[start : start + chunk_size]

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if behavior["error"]:
            raise behavior["error"]
        return Reply()

    monkeypatch.setenv("STT_SERVICE_URL", SERVICE)
    monkeypatch.setattr("google.oauth2.id_token.fetch_id_token", token)
    monkeypatch.setattr("requests.post", post)
    return calls, tokens, behavior


def submit(client, session_id, org, *, content=b"synthetic-audio", mime="audio/webm", lang="ru"):
    return client.post(
        f"/sessions/{session_id}/transcriptions?language={lang}",
        headers={"X-Organization-ID": org},
        files={"audio": ("speech.webm", content, mime)},
    )


def row_counts(engine):
    with engine.connect() as db:
        return {
            name: db.execute(text(f'SELECT count(*) FROM "{name}"')).scalar()
            for name in ("message", "specification_revision", "asset", "generation_run")
        }


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_transcription_is_editable_text_only(client, engine, speech_transport, lang):
    calls, tokens, behavior = speech_transport
    if lang == "en":
        behavior["body"] = json.dumps({**RESULT, "text": "I want a ring."}).encode()
    org, _, session = create_hierarchy(client, locale=lang)
    sid = session.json()["session_id"]
    before = row_counts(engine)
    result = submit(client, sid, org, lang=lang)
    assert result.status_code == 200
    assert result.json()["text"]
    assert row_counts(engine) == before  # No Message, revision, Asset or generation write.
    assert tokens == [SERVICE]
    url, kwargs = calls[0]
    assert url == SERVICE + "/internal/v1/transcriptions"
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-private-token"
    assert kwargs["headers"]["Content-Type"] == "audio/webm"
    assert kwargs["params"] == {"language": lang}
    assert kwargs["data"] == b"synthetic-audio"
    assert kwargs["stream"] and not kwargs["allow_redirects"]
    assert "synthetic-private-token" not in result.text


def test_transcription_auth_and_session_scope_before_provider(client, speech_transport):
    calls, tokens, _ = speech_transport
    org, _, session = create_hierarchy(client)
    sid = session.json()["session_id"]
    other_org, _, _ = create_hierarchy(client)
    assert submit(client, sid, other_org).status_code == 404
    assert submit(client, str(uuid4()), org).status_code == 404
    client.headers["Authorization"] = "Bearer test-stranger"
    assert submit(client, sid, org).status_code == 404
    client.headers.pop("Authorization")
    assert submit(client, sid, org).status_code == 401
    assert calls == tokens == []


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("mime", 415, "unsupported_audio"),
        ("language", 422, "unsupported_language"),
        ("empty", 413, "audio_too_large"),
        ("oversize", 413, "audio_too_large"),
        ("url", 503, "stt_unavailable"),
    ],
)
def test_transcription_rejects_invalid_inputs(
    client, speech_transport, monkeypatch, case, status, code
):
    calls, tokens, _ = speech_transport
    org, _, session = create_hierarchy(client)
    kwargs = {}
    if case == "mime":
        kwargs["mime"] = "audio/mp4"
    elif case == "language":
        kwargs["lang"] = "he"
    elif case == "empty":
        kwargs["content"] = b""
    elif case == "oversize":
        kwargs["content"] = b"x" * (11 * 1024 * 1024)
    else:
        monkeypatch.setenv("STT_SERVICE_URL", "https://attacker.example")
    response = submit(client, session.json()["session_id"], org, **kwargs)
    assert response.status_code == status
    assert response.json()["error"] == code
    assert calls == tokens == []


@pytest.mark.parametrize(
    "case", ["403", "redirect", "malformed", "large", "array", "schema", "token", "timeout"]
)
def test_transcription_upstream_failures_are_bounded_redacted(
    client, speech_transport, monkeypatch, case
):
    _, _, behavior = speech_transport
    if case in {"403", "redirect"}:
        behavior["status"] = 403 if case == "403" else 302
    elif case == "malformed":
        behavior["body"] = b"private-provider-body-not-json"
    elif case == "large":
        behavior["body"] = b"private-provider-body" * 10000
    elif case == "array":
        behavior["body"] = b"[]"
    elif case == "schema":
        behavior["body"] = b'{"schema_version":"other"}'
    elif case == "token":

        def failed(*args):
            raise RuntimeError("private-credential-details")

        monkeypatch.setattr("google.oauth2.id_token.fetch_id_token", failed)
    else:
        behavior["error"] = requests.Timeout("private-provider-body")
    org, _, session = create_hierarchy(client)
    response = submit(client, session.json()["session_id"], org)
    assert response.status_code == (504 if case == "timeout" else 503)
    assert response.json()["error"] == ("stt_timeout" if case == "timeout" else "stt_unavailable")
    assert "private" not in response.text


def test_silence_does_not_submit_a_message(client, engine, speech_transport):
    speech_transport[2]["body"] = json.dumps({**RESULT, "status": "silence", "text": ""}).encode()
    org, _, session = create_hierarchy(client)
    before = row_counts(engine)
    response = submit(client, session.json()["session_id"], org)
    assert response.status_code == 200
    assert response.json()["status"] == "silence"
    assert response.json()["text"] == ""
    assert row_counts(engine) == before


def test_private_upstream_fields_never_reach_browser(client, speech_transport):
    speech_transport[2]["body"] = json.dumps(
        {**RESULT, "authorization": "synthetic-private-token", "internal_url": SERVICE}
    ).encode()
    org, _, session = create_hierarchy(client)
    response = submit(client, session.json()["session_id"], org)
    assert response.status_code == 200
    assert response.json() == RESULT
    assert "synthetic-private-token" not in response.text
    assert SERVICE not in response.text
