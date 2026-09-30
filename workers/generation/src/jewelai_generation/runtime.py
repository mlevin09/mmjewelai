"""Private HTTP delivery and production composition for generation tasks."""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import FastAPI, Response
from jewelai_assets import PrivateObjectStore
from jewelai_assets_gcs import GcsAssetStorageConfig, GcsPrivateObjectStore
from jewelai_generation_queue import GenerationTaskEnvelope
from jewelai_model_gateway import ImageGenerationExecutor
from jewelai_model_gateway_google import (
    GoogleGenerativeLanguageConfig,
    GoogleGenerativeLanguageImageAdapter,
)
from jewelai_model_gateway_openai import OpenAIImageGenerationAdapter, OpenAIImageProviderConfig
from jewelai_persistence import (
    NotFoundError,
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)

from .logging import configure_worker_logger, log_event
from .service import ExecutorRegistry, execute_generation_run_with_assets


@dataclass(frozen=True)
class GenerationWorkerSettings:
    database_url: str
    gcs_asset_bucket: str
    openai_allowed_models: tuple[str, ...] = ()
    google_allowed_models: tuple[str, ...] = ()
    google_api_key: str | None = field(default=None, repr=False, compare=False)
    gcp_project_id: str | None = None
    openai_timeout_seconds: float = 180
    google_timeout_seconds: float = 180
    environment: str = "development"

    @classmethod
    def from_environment(cls) -> "GenerationWorkerSettings":
        openai_models = tuple(
            model.strip()
            for model in os.getenv("OPENAI_IMAGE_ALLOWED_MODELS", "").split(",")
            if model.strip()
        )
        google_models_raw = os.getenv("GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS", "")
        google_models = tuple(google_models_raw.split(",")) if google_models_raw else ()
        database_url = os.getenv("DATABASE_URL")
        bucket = os.getenv("GCS_ASSET_BUCKET")
        google_api_key = os.getenv("GOOGLE_GENERATIVE_LANGUAGE_API_KEY")
        if not database_url or not bucket or not (openai_models or google_models):
            raise ValueError(
                "DATABASE_URL, GCS_ASSET_BUCKET, and at least one provider model allowlist "
                "are required"
            )
        google_timeout_seconds = float(
            os.getenv("GOOGLE_GENERATIVE_LANGUAGE_TIMEOUT_SECONDS", "180")
        )
        if google_models and (not google_api_key or google_api_key != google_api_key.strip()):
            raise ValueError(
                "An exact GOOGLE_GENERATIVE_LANGUAGE_API_KEY is required when Google models "
                "are enabled"
            )
        if google_models:
            GoogleGenerativeLanguageConfig(
                allowed_models=google_models,
                timeout_seconds=google_timeout_seconds,
            )
        return cls(
            database_url=database_url,
            gcs_asset_bucket=bucket,
            openai_allowed_models=openai_models,
            google_allowed_models=google_models,
            google_api_key=google_api_key if google_models else None,
            gcp_project_id=os.getenv("GCP_PROJECT_ID"),
            openai_timeout_seconds=float(os.getenv("OPENAI_IMAGE_TIMEOUT_SECONDS", "180")),
            google_timeout_seconds=google_timeout_seconds,
            environment=os.getenv("JEWELAI_ENVIRONMENT", "development"),
        )


def create_worker_app(
    settings: GenerationWorkerSettings | None = None,
    *,
    repository: PersistenceRepository | None = None,
    executor: ImageGenerationExecutor | None = None,
    google_executor: ImageGenerationExecutor | None = None,
    object_store: PrivateObjectStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or GenerationWorkerSettings.from_environment()
    repository = repository or PersistenceRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    executor_map: dict[str, ImageGenerationExecutor] = {}
    if executor is not None:
        executor_map["openai"] = executor
    elif settings.openai_allowed_models:
        executor_map["openai"] = OpenAIImageGenerationAdapter(
            OpenAIImageProviderConfig(
                allowed_models=settings.openai_allowed_models,
                timeout_seconds=settings.openai_timeout_seconds,
            )
        )
    if google_executor is not None:
        executor_map["google"] = google_executor
    elif settings.google_allowed_models:
        if settings.google_api_key is None:
            raise ValueError(
                "GOOGLE_GENERATIVE_LANGUAGE_API_KEY is required when Google models are enabled"
            )
        executor_map["google"] = GoogleGenerativeLanguageImageAdapter(
            GoogleGenerativeLanguageConfig(
                allowed_models=settings.google_allowed_models,
                timeout_seconds=settings.google_timeout_seconds,
            ),
            api_key=settings.google_api_key,
        )
    if not executor_map:
        raise ValueError("At least one image generation provider must be configured")
    object_store = object_store or GcsPrivateObjectStore(
        GcsAssetStorageConfig(
            bucket_name=settings.gcs_asset_bucket,
            project_id=settings.gcp_project_id,
        )
    )
    executors = ExecutorRegistry(executor_map)
    app = FastAPI(title="JewelAI Generation Worker", version="1.0.0")
    logger = configure_worker_logger()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/internal/generation-tasks/execute")
    def execute(task: GenerationTaskEnvelope, response: Response):
        started = time.perf_counter()
        run_id = str(task.generation_run_id)
        log_event(
            logger,
            "generation_task_received",
            service="generation-worker",
            environment=settings.environment,
            generation_run_id=run_id,
        )
        try:
            outcome = execute_generation_run_with_assets(
                repository,
                session_id=task.session_id,
                generation_run_id=task.generation_run_id,
                organization_id=task.organization_id,
                executors=executors,
                object_store=object_store,
                object_reader=object_store,
                clock=clock,
            )
        except NotFoundError:
            log_event(
                logger,
                "generation_task_not_claimed",
                service="generation-worker",
                environment=settings.environment,
                generation_run_id=run_id,
                disposition="not_found",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            response.status_code = 204
            return None
        except Exception as exc:
            log_event(
                logger,
                "generation_task_failed",
                service="generation-worker",
                environment=settings.environment,
                generation_run_id=run_id,
                error_code=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            response.status_code = 500
            return {
                "generation_run_id": run_id,
                "disposition": "failed",
                "error_code": "worker_unavailable",
            }
        event = (
            "generation_task_not_claimed"
            if outcome.disposition == "not_claimed"
            else "generation_task_failed"
            if outcome.disposition in {"failed", "materialization_failed"}
            else "generation_task_finished"
        )
        fields = {
            "service": "generation-worker",
            "environment": settings.environment,
            "generation_run_id": run_id,
            "disposition": outcome.disposition,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        if event == "generation_task_failed":
            fields["error_code"] = (
                outcome.run.error_code.value if outcome.run.error_code else "unknown"
            )
        log_event(logger, event, **fields)
        return {
            "generation_run_id": str(task.generation_run_id),
            "disposition": outcome.disposition,
        }

    return app


create_app = create_worker_app
