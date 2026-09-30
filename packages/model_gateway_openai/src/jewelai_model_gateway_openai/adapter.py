"""Production OpenAI Images API adapter with bounded transient output retrieval."""

import base64
import binascii
import logging
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

_LOGGER = logging.getLogger("jewelai.generation.openai")


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
        except openai.AuthenticationError as exc:
            self._log_upstream_failure(request, "upstream_auth", exc)
            raise GatewayUnavailableError from exc
        except openai.PermissionDeniedError as exc:
            self._log_upstream_failure(request, "upstream_permission", exc)
            raise GatewayUnavailableError from exc
        except openai.NotFoundError as exc:
            self._log_upstream_failure(request, "upstream_not_found", exc)
            raise ProviderRejectedError from exc
        except openai.RateLimitError as exc:
            self._log_upstream_failure(request, "upstream_rate_limited", exc)
            raise GatewayUnavailableError from exc
        except openai.APITimeoutError as exc:
            self._log_upstream_failure(request, "upstream_timeout", exc)
            raise GatewayTimeoutError from exc
        except openai.APIConnectionError as exc:
            self._log_upstream_failure(request, "upstream_connection", exc)
            raise GatewayUnavailableError from exc
        except openai.InternalServerError as exc:
            self._log_upstream_failure(request, "upstream_5xx", exc)
            raise GatewayUnavailableError from exc
        except openai.BadRequestError as exc:
            self._log_upstream_failure(request, "upstream_other", exc)
            raise ProviderRejectedError from exc
        except openai.APIStatusError as exc:
            classification = "upstream_5xx" if exc.status_code >= 500 else "upstream_other"
            self._log_upstream_failure(request, classification, exc)
            if 400 <= exc.status_code < 500:
                raise ProviderRejectedError from exc
            raise GatewayUnavailableError from exc
        except openai.OpenAIError as exc:
            self._log_upstream_failure(request, "upstream_other", exc)
            raise GatewayUnavailableError from exc
        except Exception as exc:
            self._log_upstream_failure(request, "upstream_other", exc)
            raise GatewayUnavailableError from exc

        try:
            return self._execution_from_response(request, response)
        except InvalidProviderResponseError:
            raise
        except Exception as exc:
            raise InvalidProviderResponseError from exc

    @staticmethod
    def _log_upstream_failure(
        request: GenerationRequest,
        classification: str,
        error: Exception,
    ) -> None:
        status_code = getattr(error, "status_code", None)
        fields = {
            "event": "openai_generation_upstream_failure",
            "generation_run_id": str(request.generation_run_id),
            "upstream_classification": classification,
        }
        if isinstance(status_code, int):
            fields["upstream_http_status"] = status_code
        _LOGGER.info(
            "openai generation upstream failure",
            extra={"jewelai_fields": fields},
        )

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
