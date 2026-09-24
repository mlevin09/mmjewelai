"""One-shot, idempotent generation-run orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from jewelai_model_gateway import (
    GatewayError,
    GatewayUnavailableError,
    GenerationErrorCode,
    GenerationRequest,
    GenerationRun,
    ImageGenerationGateway,
    validate_generation_result,
)
from jewelai_persistence import GenerationStateConflictError, PersistenceRepository
from pydantic import BaseModel, ConfigDict


class ExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["succeeded", "failed", "not_claimed"]
    run: GenerationRun


class GatewayRegistry:
    def __init__(self, gateways: dict[str, ImageGenerationGateway]):
        self._gateways = MappingProxyType(dict(gateways))

    def get(self, provider: str) -> ImageGenerationGateway:
        try:
            return self._gateways[provider]
        except KeyError as exc:
            raise GatewayUnavailableError from exc


def execute_generation_run(
    repository: PersistenceRepository,
    *,
    session_id: UUID,
    generation_run_id: UUID,
    organization_id: UUID,
    gateways: GatewayRegistry,
    clock: Callable[[], datetime] | None = None,
) -> ExecutionOutcome:
    clock = clock or (lambda: datetime.now(UTC))
    try:
        claimed = repository.claim_generation_run(
            session_id, generation_run_id, organization_id, clock()
        )
    except GenerationStateConflictError:
        existing = repository.get_generation_run(session_id, generation_run_id, organization_id)
        return ExecutionOutcome(disposition="not_claimed", run=existing)

    _, compiled = repository.get_prompt_revision(
        session_id, claimed.prompt_revision_id, organization_id
    )
    if compiled.content_hash != claimed.prompt_content_hash:
        return _fail(
            repository,
            claimed,
            organization_id,
            GenerationErrorCode.GATEWAY_CONTRACT_VIOLATION,
            "Stored prompt lineage failed integrity validation",
            clock,
        )
    request = GenerationRequest(
        generation_run_id=claimed.generation_run_id,
        prompt_revision_id=claimed.prompt_revision_id,
        compiled_prompt=compiled,
        provider=claimed.provider,
        model=claimed.model,
        configuration=claimed.configuration,
    )
    try:
        gateway = gateways.get(claimed.provider)
        untrusted = gateway.generate(request)
        result = validate_generation_result(request, untrusted)
        completed = repository.complete_generation_run(
            session_id,
            generation_run_id,
            organization_id,
            result,
            clock(),
        )
        return ExecutionOutcome(disposition="succeeded", run=completed)
    except GatewayError as exc:
        return _fail(
            repository,
            claimed,
            organization_id,
            GenerationErrorCode(exc.code),
            exc.safe_detail,
            clock,
        )
    except Exception:
        return _fail(
            repository,
            claimed,
            organization_id,
            GenerationErrorCode.GATEWAY_UNAVAILABLE,
            "The generation gateway failed safely",
            clock,
        )


def _fail(
    repository: PersistenceRepository,
    run: GenerationRun,
    organization_id: UUID,
    code: GenerationErrorCode,
    detail: str,
    clock: Callable[[], datetime],
) -> ExecutionOutcome:
    failed = repository.fail_generation_run(
        run.session_id,
        run.generation_run_id,
        organization_id,
        code,
        detail,
        clock(),
    )
    return ExecutionOutcome(disposition="failed", run=failed)
