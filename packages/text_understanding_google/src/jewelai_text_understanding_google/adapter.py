"""One-call Google adapter that emits an untrusted ParserCandidate."""

import json
from typing import Literal

import httpx
from jewelai_parser import ParserCandidate, ParserTarget
from pydantic import ValidationError

from .config import GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT, GoogleTextUnderstandingConfig
from .contracts import (
    TextUnderstandingInvalidResponseError,
    TextUnderstandingRejectedError,
    TextUnderstandingTimeoutError,
    TextUnderstandingUnavailableError,
)

_SYSTEM_INSTRUCTION = """You extract explicitly stated jewelry facts into a ParserCandidate.
Return JSON only. Use schema_version 1.0.0 and only the supplied supported targets.
Preserve human terminology in term.text; do not translate it to an ID or guess a synonym.
Never infer or fabricate missing dimensions, weight, purity, quantity, style, materials,
or defaults.
Never add confirmation, lock, authorization, question-selection, derived, or assumed state.
Never create a side-stone group. Omit every fact that is not explicit in the message.
The result is untrusted and will be validated and normalized deterministically."""
_SUPPORTED_JSON_SCHEMA_KEYS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "anyOf",
        "description",
        "enum",
        "format",
        "items",
        "maxItems",
        "maximum",
        "minItems",
        "minimum",
        "oneOf",
        "prefixItems",
        "properties",
        "required",
        "title",
        "type",
    }
)


def _google_response_schema() -> dict:
    """Derive Google's supported JSON Schema subset from the authoritative contract."""

    def sanitize(value):
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if not isinstance(value, dict):
            return value
        sanitized = {}
        for key, item in value.items():
            if key == "const":
                sanitized["enum"] = [item]
            elif key == "exclusiveMinimum":
                sanitized.setdefault("minimum", item)
            elif key in {"$defs", "properties"}:
                sanitized[key] = {name: sanitize(schema) for name, schema in item.items()}
            elif key in _SUPPORTED_JSON_SCHEMA_KEYS:
                sanitized[key] = sanitize(item)
        return sanitized

    return sanitize(ParserCandidate.model_json_schema())


class GoogleTextUnderstandingAdapter:
    """Convert one persisted message into one strictly validated untrusted candidate."""

    def __init__(
        self,
        config: GoogleTextUnderstandingConfig,
        *,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key or api_key != api_key.strip():
            raise ValueError("Google Generative Language API key must be non-empty and exact")
        self.config = config
        self._api_key = api_key
        self._client = client or httpx.Client(
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )

    def understand(self, message: str, locale: Literal["en", "ru"]) -> ParserCandidate:
        if not isinstance(message, str) or not message or message != message.strip():
            raise ValueError("Understanding input must be a non-empty exact message")
        if locale not in {"en", "ru"}:
            raise ValueError("Understanding locale must be en or ru")
        endpoint = GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT.format(model=self.config.model)
        payload = {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                f"Session locale: {locale}. Supported targets: "
                                f"{', '.join(target.value for target in ParserTarget)}.\n"
                                f"Message:\n{message}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseJsonSchema": _google_response_schema(),
            },
        }
        try:
            response = self._client.post(
                endpoint,
                headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
                json=payload,
            )
        except httpx.TimeoutException:
            raise TextUnderstandingTimeoutError("Text understanding timed out") from None
        except httpx.RequestError:
            raise TextUnderstandingUnavailableError("Text understanding is unavailable") from None
        except Exception:
            raise TextUnderstandingUnavailableError("Text understanding is unavailable") from None
        if response.status_code == 429 or response.status_code >= 500:
            raise TextUnderstandingUnavailableError("Text understanding is unavailable")
        if 400 <= response.status_code < 500:
            raise TextUnderstandingRejectedError("Text understanding request was rejected")
        if not 200 <= response.status_code < 300:
            raise TextUnderstandingUnavailableError("Text understanding is unavailable")
        if len(response.content) > self.config.max_response_bytes:
            raise TextUnderstandingInvalidResponseError("Text understanding returned invalid data")
        try:
            body = response.json()
            candidates = body["candidates"]
            parts = candidates[0]["content"]["parts"]
            texts = [
                part["text"]
                for part in parts
                if isinstance(part, dict) and "text" in part and part.get("thought") is not True
            ]
            if len(texts) != 1 or not isinstance(texts[0], str):
                raise KeyError
            raw = json.loads(texts[0])
            return ParserCandidate.model_validate(raw)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError):
            raise TextUnderstandingInvalidResponseError(
                "Text understanding returned invalid data"
            ) from None
