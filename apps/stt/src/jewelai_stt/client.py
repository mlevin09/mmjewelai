"""Server-side direct Cloud Run client; not wired to public API or Prompt Enrichment."""

import re

import httpx

from .audio import FORMATS, MAX_BYTES, SttError


def _id_token(audience: str) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import fetch_id_token

    return fetch_id_token(Request(), audience)


class SttClient:
    def __init__(self, service_url: str, *, token_factory=_id_token, transport=None):
        if not re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.run\.app", service_url):
            raise ValueError("invalid_stt_service_url")
        self.service_url = service_url
        self.token_factory = token_factory
        self.transport = transport

    def transcribe(self, content: bytes, content_type: str, language: str | None = None) -> dict:
        if content_type not in FORMATS or language not in (None, "ru", "en"):
            raise SttError("unsupported_audio")
        if len(content) > MAX_BYTES:
            raise SttError("audio_too_large", 413)
        try:
            token = self.token_factory(self.service_url)
            with httpx.Client(
                transport=self.transport, timeout=58, follow_redirects=False, trust_env=False
            ) as client:
                with client.stream(
                    "POST",
                    self.service_url + "/internal/v1/transcriptions",
                    params={"language": language} if language else {},
                    content=content,
                    headers={"Authorization": "Bearer " + token, "Content-Type": content_type},
                ) as result:
                    if result.status_code in (401, 403):
                        raise SttError("stt_access_denied", 503)
                    if result.status_code != 200:
                        raise SttError("stt_unavailable", 503)
                    body_bytes = bytearray()
                    for chunk in result.iter_bytes():
                        if len(body_bytes) + len(chunk) > 65536:
                            raise SttError("stt_unavailable", 503)
                        body_bytes.extend(chunk)
                    import json

                    body = json.loads(body_bytes)
            if (
                body.get("schema_version") != "1.0.0"
                or body.get("status") not in ("transcribed", "silence")
                or not isinstance(body.get("text"), str)
                or len(body["text"]) > 8192
            ):
                raise SttError("stt_unavailable", 503)
            return body
        except httpx.TimeoutException:
            raise SttError("stt_timeout", 504) from None
        except SttError:
            raise
        except Exception:
            # Credential acquisition, network and invalid JSON: never expose response/token details.
            raise SttError("stt_unavailable", 503) from None
