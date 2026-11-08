import array
import hashlib
import io
import json
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient

from jewelai_stt.app import create_app
from jewelai_stt.artifacts import MODEL_ID, REVISION, verify_artifacts
from jewelai_stt.audio import MAX_BYTES, Audio, SttError, decode_audio
from jewelai_stt.client import SttClient
from jewelai_stt.engine import LocalEngine, _model_process


def wav(seconds=0.1, *, silence=False):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes((b"\0\0" if silence else b"\0\x10") * int(seconds * 16000))
    return output.getvalue()


class FakeEngine:
    """Contract fake, not evidence of Qwen speech recognition or accuracy."""

    ready = False
    calls = 0

    def start(self):
        self.ready = True

    def close(self):
        self.ready = False

    def transcribe(self, pcm, language):
        self.calls += 1
        assert pcm
        return ("Хочу кольцо.", "ru") if language == "ru" else ("I want a ring.", "en")


@pytest.mark.parametrize("language,expected", [("ru", "Хочу кольцо."), ("en", "I want a ring.")])
def test_http_contract_with_real_decoder_fake_recognizer(language, expected, tmp_path, caplog):
    engine = FakeEngine()
    before = list(tmp_path.iterdir())
    with TestClient(create_app(engine=engine)) as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/internal/v1/transcriptions?language=" + language,
            content=wav(),
            headers={"content-type": "audio/wav"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["text"] == expected
        assert result["schema_version"] == "1.0.0"
        assert result["model_revision"] == REVISION
        assert result["duration_ms"] == 100
        assert result["language"] == language
        assert result["status"] == "transcribed"
        assert "session_id" not in result
        assert client.get("/docs").status_code == 404
    assert engine.calls == 1 and not engine.ready
    assert list(tmp_path.iterdir()) == before  # implementation uses pipes, no audio temp files
    assert expected not in caplog.text


def test_digital_silence_skips_model():
    engine = FakeEngine()
    with TestClient(create_app(engine=engine)) as client:
        response = client.post(
            "/internal/v1/transcriptions",
            content=wav(silence=True),
            headers={"content-type": "audio/wav"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "silence" and response.json()["text"] == ""
    assert engine.calls == 0


@pytest.mark.parametrize(
    "body,mime,suffix,status,code",
    [
        (b"garbage", "audio/wav", "", 422, "invalid_audio"),
        (b"", "audio/wav", "", 422, "invalid_audio"),
        (b"https://private.example/audio", "application/json", "", 415, "unsupported_audio"),
        (b"x" * (MAX_BYTES + 1), "audio/wav", "", 413, "audio_too_large"),
        (wav(60.1), "audio/wav", "", 413, "audio_too_long"),
        (wav(), "audio/ogg", "", 422, "invalid_audio"),
        (wav(), "audio/wav", "?language=he", 422, "unsupported_language"),
        (wav(), "audio/wav", "?url=https://example.test", 400, "invalid_request"),
    ],
    ids=[
        "invalid",
        "empty",
        "url",
        "oversized",
        "overlong",
        "mime_mismatch",
        "language",
        "url_query",
    ],
)
def test_http_rejections(body, mime, suffix, status, code):
    engine = FakeEngine()
    with TestClient(create_app(engine=engine)) as client:
        response = client.post(
            "/internal/v1/transcriptions" + suffix,
            content=body,
            headers={"content-type": mime},
        )
    assert response.status_code == status
    assert response.json() == {"error": {"code": code}}
    assert engine.calls == 0


@pytest.mark.parametrize("format,mime", [("webm", "audio/webm"), ("ogg", "audio/ogg")])
def test_real_opus_decoding(format, mime):
    encoded = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-loglevel",
            "quiet",
            "-i",
            "pipe:0",
            "-c:a",
            "libopus",
            "-f",
            format,
            "pipe:1",
        ],
        input=wav(),
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout
    decoded = decode_audio(encoded, mime)
    assert 90 <= decoded.duration_ms <= 110
    assert not decoded.silent


def test_decode_timeout_redacted(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("PRIVATE_AUDIO", 8)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(SttError, match="^audio_decode_timeout$") as error:
        decode_audio(wav(), "audio/wav")
    assert error.value.status == 504


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "stt_access_denied"),
        (403, "stt_access_denied"),
        (500, "stt_unavailable"),
        (302, "stt_unavailable"),
    ],
)
def test_client_auth_and_upstream_errors_redacted(status, expected):
    def handler(request):
        assert request.headers["authorization"] == "Bearer TEST_TOKEN"
        assert request.url.path == "/internal/v1/transcriptions"
        assert request.content == wav()
        return httpx.Response(status, text="PRIVATE_RESPONSE TEST_TOKEN")

    client = SttClient(
        "https://stt-123.europe-west1.run.app",
        token_factory=lambda audience: "TEST_TOKEN",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SttError, match="^" + expected + "$"):
        client.transcribe(wav(), "audio/wav")


def test_client_success_and_audience():
    audiences = []

    def token(audience):
        audiences.append(audience)
        return "TEST_TOKEN"

    client = SttClient(
        "https://stt-123.europe-west1.run.app",
        token_factory=token,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "schema_version": "1.0.0",
                    "status": "transcribed",
                    "text": "Test text",
                },
            )
        ),
    )
    assert client.transcribe(wav(), "audio/wav")["text"] == "Test text"
    assert audiences == [client.service_url]


@pytest.mark.parametrize(
    "url",
    [
        "http://stt.run.app",
        "https://evil.test",
        "https://x.run.app/?key=x",
        "https://x.run.app@evil.test",
        "https://x.run.app:8443",
    ],
)
def test_client_refuses_arbitrary_destinations(url):
    with pytest.raises(ValueError, match="invalid_stt_service_url"):
        SttClient(url)


def test_client_credential_failure_has_no_sensitive_details():
    def token(_):
        raise RuntimeError("SECRET token=abc")

    with pytest.raises(SttError, match="^stt_unavailable$"):
        SttClient("https://stt-123.europe-west1.run.app", token_factory=token).transcribe(
            wav(), "audio/wav"
        )


def bundle(root):
    content = b"synthetic model placeholder; never used for actual inference"
    (root / "weights.safetensors").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    data = {"model_id": MODEL_ID, "revision": REVISION, "files": {"weights.safetensors": digest}}
    (root / "manifest.json").write_text(json.dumps(data))
    return {"weights.safetensors": digest}


def test_model_bundle_roundtrip_and_tamper(tmp_path):
    weights = bundle(tmp_path)
    verify_artifacts(tmp_path, weights=weights)
    (tmp_path / "weights.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="invalid_model_bundle"):
        verify_artifacts(tmp_path, weights=weights)


@pytest.mark.parametrize("change", ["revision", "missing", "extra", "symlink", "manifest_tamper"])
def test_bundle_fail_closed(tmp_path, change):
    weights = bundle(tmp_path)
    if change == "revision":
        path = tmp_path / "manifest.json"
        path.write_text(path.read_text().replace(REVISION, "main"))
    elif change == "missing":
        (tmp_path / "weights.safetensors").unlink()
    elif change == "extra":
        (tmp_path / "unexpected").write_text("x")
    elif change == "symlink":
        (tmp_path / "weights.safetensors").rename(tmp_path / "real")
        (tmp_path / "weights.safetensors").symlink_to(tmp_path / "real")
    else:
        path = tmp_path / "manifest.json"
        path.write_text(path.read_text().replace(next(iter(weights.values())), "0" * 64))
    with pytest.raises(ValueError):
        verify_artifacts(tmp_path, weights=weights)


def test_worker_uses_only_verified_local_artifacts(monkeypatch, tmp_path):
    calls = []
    model = SimpleNamespace(
        transcribe=lambda **kw: [SimpleNamespace(text="Test", language="English")]
    )

    def load(path, **kwargs):
        calls.append((path, kwargs))
        return model

    monkeypatch.setattr("jewelai_stt.engine.verify_artifacts", lambda p: calls.append(p))
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            bfloat16="BF16",
            set_num_threads=lambda _: None,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "qwen_asr",
        SimpleNamespace(
            Qwen3ASRModel=SimpleNamespace(from_pretrained=load),
        ),
    )

    class Connection:
        results = []
        count = 0

        def send(self, value):
            self.results.append(value)

        def recv(self):
            self.count += 1
            if self.count > 1:
                assert "pcm" not in sys._getframe(1).f_locals
                assert "result" not in sys._getframe(1).f_locals
                raise EOFError
            return array.array("f", [0.25]).tobytes(), "en"

    connection = Connection()
    _model_process(connection, str(tmp_path))
    assert calls[0] == tmp_path
    assert calls[1][0] == str(tmp_path) and calls[1][1]["local_files_only"] is True
    assert calls[1][1]["max_inference_batch_size"] == 1
    assert connection.results == [("ready",), ("result", "Test", "en")]


def test_timeout_terminates_model_and_fails_readiness():
    events = []
    engine = LocalEngine()
    engine._ready = True
    engine.connection = SimpleNamespace(
        send=lambda _: None,
        poll=lambda _: False,
        close=lambda: events.append("closed"),
    )
    engine.process = SimpleNamespace(
        is_alive=lambda: "terminated" not in events,
        terminate=lambda: events.append("terminated"),
        join=lambda _: None,
    )
    with pytest.raises(SttError, match="^stt_timeout$"):
        engine.transcribe(b"pcm", "en")
    assert events == ["terminated", "closed"] and not engine.ready


@pytest.mark.parametrize("code,status", [("stt_timeout", 504), ("stt_unavailable", 503)])
def test_http_model_failure_is_redacted(code, status):
    class Broken(FakeEngine):
        def transcribe(self, *_):
            raise SttError(code, status)

    with TestClient(create_app(engine=Broken())) as client:
        response = client.post(
            "/internal/v1/transcriptions",
            content=wav(),
            headers={"content-type": "audio/wav"},
        )
    assert response.status_code == status and response.json() == {"error": {"code": code}}


def test_runtime_has_no_audio_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert decode_audio(wav(), "audio/wav").duration_ms == 100
    with pytest.raises(SttError):
        decode_audio(b"invalid", "audio/wav")
    assert list(tmp_path.iterdir()) == []


def test_engine_busy_and_unavailable():
    engine = LocalEngine()
    with pytest.raises(SttError, match="stt_unavailable"):
        engine.transcribe(b"pcm", None)
    engine.lock.acquire()
    try:
        with pytest.raises(SttError, match="stt_busy"):
            engine.transcribe(b"pcm", None)
    finally:
        engine.lock.release()


def test_infrastructure_disabled_private_and_no_gateway():
    root = Path(__file__).resolve().parents[3]
    source = (root / "infra/terraform/preprod/stt.tf").read_text()
    services = (root / "infra/terraform/preprod/services.tf").read_text()
    assert 'default     = ""' in source
    assert "INGRESS_TRAFFIC_INTERNAL_ONLY" in source
    assert "invoker_iam_disabled = false" in source
    assert 'members  = ["serviceAccount:${google_service_account.runtime["api"].email}"]' in source
    assert 'egress = "ALL_TRAFFIC"' in source
    assert '"0.0.0.0/0"' in source and '"::/0"' in source
    assert 'dns_name        = "*."' in source
    assert 'stack_type               = "IPV4_ONLY"' in source
    assert 'egress = "PRIVATE_RANGES_ONLY"' in services
    for forbidden in (
        "allUsers",
        "allAuthenticatedUsers",
        '"google_compute_router"',
        '"google_compute_router_nat"',
        '"google_compute_forwarding_rule"',
        '"google_secret_manager_secret_version"',
    ):
        assert forbidden not in source


def test_deployment_fingerprint_binds_optional_stt_inputs():
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/deploy-preprod.yml").read_text()
    assert workflow.count('"${TF_VAR_stt_image}" "${TF_VAR_stt_resource_approval_reference}"') == 2
    assert workflow.count("TF_VAR_stt_image: ${{ vars.STT_IMAGE }}") == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_pcm_is_rejected(value):
    with pytest.raises(SttError, match="invalid_audio"):
        Audio(array.array("f", [value]).tobytes())


def test_dead_model_is_not_ready():
    engine = LocalEngine()
    engine._ready = True
    engine.process = SimpleNamespace(is_alive=lambda: False)
    assert not engine.ready


@pytest.mark.parametrize("body", [b"not json", b"x" * 65537], ids=["invalid_json", "oversized"])
def test_client_bounds_untrusted_response(body):
    client = SttClient(
        "https://stt-123.europe-west1.run.app",
        token_factory=lambda _: "TEST_TOKEN",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)),
    )
    with pytest.raises(SttError, match="stt_unavailable"):
        client.transcribe(wav(), "audio/wav")


def test_client_timeout_is_redacted():
    def timeout(_):
        raise httpx.ReadTimeout("PRIVATE_AUDIO TEST_TOKEN")

    client = SttClient(
        "https://stt-123.europe-west1.run.app",
        token_factory=lambda _: "TEST_TOKEN",
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(SttError, match="^stt_timeout$"):
        client.transcribe(wav(), "audio/wav")


def test_packaging_uses_hashes_and_offline_local_model():
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "infra/docker/stt.Dockerfile").read_text()
    assert dockerfile.count("--require-hashes") == 2
    assert "--no-build-isolation" in dockerfile
    assert "HF_HUB_OFFLINE=1" in dockerfile and "TRANSFORMERS_OFFLINE=1" in dockerfile
    assert "--no-access-log" in dockerfile and "USER 10001:10001" in dockerfile
    assert "package_model.py /opt/model" in dockerfile


def test_empty_model_result_is_silence_without_claiming_a_language():
    class Empty(FakeEngine):
        def transcribe(self, *_):
            return "", "en"

    with TestClient(create_app(engine=Empty())) as client:
        response = client.post(
            "/internal/v1/transcriptions",
            content=wav(),
            headers={"content-type": "audio/wav"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "silence"
    assert response.json()["language"] is None
