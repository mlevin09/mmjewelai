"""Google Generative Language REST adapter with bounded transient image retrieval."""

import base64
import binascii
from typing import Any

import httpx
from jewelai_model_gateway import (
    GatewayTimeoutError,
    GatewayUnavailableError,
    GeneratedOutputDescriptor,
    GenerationExecution,
    GenerationRequest,
    GenerationResult,
    ImageGenerationEditInput,
    InvalidProviderResponseError,
    ProviderRejectedError,
    RetrievedImageOutput,
)

from .config import (
    GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT,
    GOOGLE_PROVIDER_ID,
    GoogleGenerativeLanguageConfig,
)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_SUPPORTED_IMAGE_CONTENT_TYPES = frozenset(("image/png", "image/jpeg", "image/webp"))


class GoogleGenerativeLanguageImageAdapter:
    """Translate one immutable request into exactly one GenerateContent call."""

    def __init__(
        self,
        config: GoogleGenerativeLanguageConfig,
        *,
        api_key: str,
        client: httpx.Client | None = None,
    ):
        if not isinstance(api_key, str) or not api_key or api_key != api_key.strip():
            raise ValueError("Google Generative Language API key must be non-empty and exact")
        self.config = config
        self._api_key = api_key
        self._client = client or httpx.Client(
            timeout=config.timeout_seconds,
            follow_redirects=False,
        )

    def execute(
        self,
        request: GenerationRequest,
        *,
        edit_input: ImageGenerationEditInput | None = None,
    ) -> GenerationExecution:
        request = GenerationRequest.model_validate(request)
        self._validate_request(request)
        endpoint = GOOGLE_GENERATIVE_LANGUAGE_ENDPOINT.format(model=request.model)
        parts = [{"text": request.compiled_prompt.prompt_text}]
        if edit_input is not None:
            parts = [
                {
                    "text": (
                        "Edit the supplied current jewelry visualization. Apply only the explicit "
                        "change request while preserving all other visible characteristics and all "
                        "locked canonical constraints.\nCHANGE REQUEST:\n"
                        f"{edit_input.change_request}\n\n"
                        f"{request.compiled_prompt.prompt_text}"
                    )
                },
                {
                    "inlineData": {
                        "mimeType": edit_input.declared_content_type,
                        "data": base64.b64encode(edit_input.content).decode("ascii"),
                    }
                },
            ]
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        try:
            response = self._client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self._api_key,
                },
                json=payload,
            )
        except httpx.TimeoutException:
            raise GatewayTimeoutError from None
        except httpx.RequestError:
            raise GatewayUnavailableError from None
        except Exception:
            raise GatewayUnavailableError from None

        if response.status_code == 429 or response.status_code >= 500:
            raise GatewayUnavailableError
        if 400 <= response.status_code < 500:
            raise ProviderRejectedError
        if not 200 <= response.status_code < 300:
            raise GatewayUnavailableError
        max_encoded_bytes = ((self.config.max_output_bytes + 2) // 3) * 4
        if len(response.content) > max_encoded_bytes + 1_048_576:
            raise InvalidProviderResponseError

        try:
            body = response.json()
            return self._execution_from_body(request, body)
        except InvalidProviderResponseError:
            raise
        except Exception:
            raise InvalidProviderResponseError from None

    def _validate_request(self, request: GenerationRequest) -> None:
        if request.provider != GOOGLE_PROVIDER_ID:
            raise ProviderRejectedError
        if request.model not in self.config.allowed_models:
            raise ProviderRejectedError
        if request.configuration.output_count != 1:
            raise ProviderRejectedError

    def _execution_from_body(self, request: GenerationRequest, body: Any) -> GenerationExecution:
        if not isinstance(body, dict):
            raise InvalidProviderResponseError
        candidates = body.get("candidates")
        if (
            not isinstance(candidates, list)
            or not candidates
            or not isinstance(candidates[0], dict)
        ):
            raise InvalidProviderResponseError
        content = candidates[0].get("content")
        if not isinstance(content, dict):
            raise InvalidProviderResponseError
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise InvalidProviderResponseError

        inline_parts = [
            part.get("inlineData")
            for part in parts
            if isinstance(part, dict) and "inlineData" in part
        ]
        if len(inline_parts) != 1 or not isinstance(inline_parts[0], dict):
            raise InvalidProviderResponseError
        inline_data = inline_parts[0]
        content_type = inline_data.get("mimeType")
        if content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
            raise InvalidProviderResponseError
        image = self._decode_output(inline_data.get("data"))
        if not self._has_matching_signature(content_type, image):
            raise InvalidProviderResponseError

        result = GenerationResult(
            generation_run_id=request.generation_run_id,
            provider=request.provider,
            model=request.model,
            outputs=(GeneratedOutputDescriptor(ordinal=1),),
        )
        return GenerationExecution(
            result=result,
            outputs=(RetrievedImageOutput(1, None, content_type, image),),
        )

    @staticmethod
    def _has_matching_signature(content_type: str, content: bytes) -> bool:
        if content_type == "image/png":
            return content.startswith(_PNG_SIGNATURE)
        if content_type == "image/jpeg":
            return content.startswith(_JPEG_SIGNATURE)
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"

    def _decode_output(self, encoded: Any) -> bytes:
        if not isinstance(encoded, str) or not encoded:
            raise InvalidProviderResponseError
        max_encoded_bytes = ((self.config.max_output_bytes + 2) // 3) * 4
        if len(encoded) > max_encoded_bytes:
            raise InvalidProviderResponseError
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise InvalidProviderResponseError from None
        if not content or len(content) > self.config.max_output_bytes:
            raise InvalidProviderResponseError
        return content
