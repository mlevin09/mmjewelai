"""Production OpenAI Images API adapter with bounded transient output retrieval."""

import base64
import binascii
from typing import Any

import openai
from jewelai_model_gateway import (
    GatewayTimeoutError,
    GatewayUnavailableError,
    GeneratedOutputDescriptor,
    GenerationExecution,
    GenerationRequest,
    GenerationResult,
    InvalidProviderResponseError,
    ProviderRejectedError,
    RetrievedImageOutput,
)
from openai import OpenAI

from .config import OpenAIImageProviderConfig


class OpenAIImageGenerationAdapter:
    """Translate one immutable gateway request into one OpenAI Images API call."""

    def __init__(self, config: OpenAIImageProviderConfig, *, client: Any | None = None):
        self.config = config
        self._client = (
            client
            if client is not None
            else OpenAI(
                timeout=config.timeout_seconds,
                max_retries=0,
            )
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        return self.execute(request).result

    def execute(self, request: GenerationRequest) -> GenerationExecution:
        request = GenerationRequest.model_validate(request)
        self._validate_request(request)
        try:
            response = self._client.images.generate(
                model=request.model,
                prompt=request.compiled_prompt.prompt_text,
                n=request.configuration.output_count,
                output_format="png",
            )
        except openai.APITimeoutError as exc:
            raise GatewayTimeoutError from exc
        except (
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.InternalServerError,
        ) as exc:
            raise GatewayUnavailableError from exc
        except openai.BadRequestError as exc:
            raise ProviderRejectedError from exc
        except openai.APIStatusError as exc:
            if 400 <= exc.status_code < 500:
                raise ProviderRejectedError from exc
            raise GatewayUnavailableError from exc
        except openai.OpenAIError as exc:
            raise GatewayUnavailableError from exc
        except Exception as exc:
            raise GatewayUnavailableError from exc

        try:
            return self._execution_from_response(request, response)
        except InvalidProviderResponseError:
            raise
        except Exception as exc:
            raise InvalidProviderResponseError from exc

    def _validate_request(self, request: GenerationRequest) -> None:
        if request.provider != "openai":
            raise ProviderRejectedError
        if request.model not in self.config.allowed_models:
            raise ProviderRejectedError

    def _execution_from_response(
        self, request: GenerationRequest, response: Any
    ) -> GenerationExecution:
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) != request.configuration.output_count:
            raise InvalidProviderResponseError

        descriptors = []
        outputs = []
        for ordinal, item in enumerate(data, start=1):
            encoded = getattr(item, "b64_json", None)
            content = self._decode_output(encoded)
            descriptors.append(GeneratedOutputDescriptor(ordinal=ordinal))
            outputs.append(
                RetrievedImageOutput(
                    ordinal=ordinal,
                    provider_output_id=None,
                    declared_content_type="image/png",
                    content=content,
                )
            )
        result = GenerationResult(
            generation_run_id=request.generation_run_id,
            provider=request.provider,
            model=request.model,
            outputs=tuple(descriptors),
        )
        return GenerationExecution(result=result, outputs=tuple(outputs))

    def _decode_output(self, encoded: Any) -> bytes:
        if not isinstance(encoded, str) or not encoded:
            raise InvalidProviderResponseError
        max_encoded_bytes = ((self.config.max_output_bytes + 2) // 3) * 4
        if len(encoded) > max_encoded_bytes:
            raise InvalidProviderResponseError
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidProviderResponseError from exc
        if not content or len(content) > self.config.max_output_bytes:
            raise InvalidProviderResponseError
        return content
