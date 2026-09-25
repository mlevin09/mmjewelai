"""One-shot, idempotent generation-run orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal
from uuid import UUID

from jewelai_assets import (
    Asset,
    AssetContentRejectedError,
    AssetIngestionRequest,
    AssetKind,
    AssetStorageError,
    PrivateObjectStore,
    finalize_staged_asset,
    stage_asset_object,
)
from jewelai_model_gateway import (
    GatewayError,
    GatewayUnavailableError,
    GenerationErrorCode,
    GenerationRequest,
    GenerationRun,
    ImageGenerationExecutor,
    ImageGenerationGateway,
    InvalidProviderResponseError,
    validate_generation_execution,
    validate_generation_result,
)
from jewelai_persistence import GenerationStateConflictError, PersistenceRepository
from pydantic import BaseModel, ConfigDict

from .materialization import generated_asset_id


class ExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: Literal["succeeded", "failed", "materialization_failed", "not_claimed"]
    run: GenerationRun
    assets: tuple[Asset, ...] = ()


class GatewayRegistry:
    def __init__(self, gateways: dict[str, ImageGenerationGateway]):
        self._gateways = MappingProxyType(dict(gateways))

    def get(self, provider: str) -> ImageGenerationGateway:
        try:
            return self._gateways[provider]
        except KeyError as exc:
            raise GatewayUnavailableError from exc


class ExecutorRegistry:
    def __init__(self, executors: dict[str, ImageGenerationExecutor]):
        self._executors = MappingProxyType(dict(executors))

    def get(self, provider: str) -> ImageGenerationExecutor:
        try:
            return self._executors[provider]
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
    prepared = _prepare_execution(repository, session_id, generation_run_id, organization_id, clock)
    if isinstance(prepared, ExecutionOutcome):
        return prepared
    claimed, request = prepared
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


def execute_generation_run_with_assets(
    repository: PersistenceRepository,
    *,
    session_id: UUID,
    generation_run_id: UUID,
    organization_id: UUID,
    executors: ExecutorRegistry,
    object_store: PrivateObjectStore,
    clock: Callable[[], datetime] | None = None,
) -> ExecutionOutcome:
    """Execute once, durably stage all outputs, then persist success and Asset metadata."""
    clock = clock or (lambda: datetime.now(UTC))
    prepared = _prepare_execution(repository, session_id, generation_run_id, organization_id, clock)
    if isinstance(prepared, ExecutionOutcome):
        return prepared
    claimed, request = prepared

    try:
        executor = executors.get(claimed.provider)
        execution = validate_generation_execution(request, executor.execute(request))
        session = repository.get_design_session(session_id, organization_id)
        staged = []
        for output in execution.outputs:
            descriptor = execution.result.outputs[output.ordinal - 1]
            ingestion_request = AssetIngestionRequest(
                asset_id=generated_asset_id(generation_run_id, output.ordinal),
                organization_id=organization_id,
                project_id=session.project_id,
                session_id=session_id,
                kind=AssetKind.GENERATED,
                declared_content_type=output.declared_content_type,
                generation_run_id=generation_run_id,
                generation_output_ordinal=output.ordinal,
                provider_output_id=descriptor.provider_output_id,
            )
            try:
                stored_object = stage_asset_object(
                    request=ingestion_request,
                    content=output.content,
                    object_store=object_store,
                )
            except (AssetContentRejectedError, ValueError) as exc:
                raise InvalidProviderResponseError from exc
            staged.append((ingestion_request, output, stored_object))
        completed = repository.complete_generation_run(
            session_id,
            generation_run_id,
            organization_id,
            execution.result,
            clock(),
        )
    except AssetStorageError:
        return _fail(
            repository,
            claimed,
            organization_id,
            GenerationErrorCode.GATEWAY_UNAVAILABLE,
            "Generated output could not be durably staged",
            clock,
        )
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

    assets = []
    materialization_failed = False
    for ingestion_request, output, stored_object in staged:
        try:
            asset = finalize_staged_asset(
                request=ingestion_request,
                content=output.content,
                stored_object=stored_object,
                repository=repository,
                clock=clock,
            )
            assets.append(asset)
        except Exception:
            materialization_failed = True
    return ExecutionOutcome(
        disposition="materialization_failed" if materialization_failed else "succeeded",
        run=completed,
        assets=tuple(assets),
    )


def _prepare_execution(
    repository: PersistenceRepository,
    session_id: UUID,
    generation_run_id: UUID,
    organization_id: UUID,
    clock: Callable[[], datetime],
) -> tuple[GenerationRun, GenerationRequest] | ExecutionOutcome:
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
    return claimed, request


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
