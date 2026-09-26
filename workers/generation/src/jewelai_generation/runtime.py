"""Private HTTP delivery and production composition for generation tasks."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI, Response
from jewelai_assets import PrivateObjectStore
from jewelai_assets_gcs import GcsAssetStorageConfig, GcsPrivateObjectStore
from jewelai_generation_queue import GenerationTaskEnvelope
from jewelai_model_gateway import ImageGenerationExecutor
from jewelai_model_gateway_openai import OpenAIImageGenerationAdapter, OpenAIImageProviderConfig
from jewelai_persistence import (
    NotFoundError,
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)

from .service import ExecutorRegistry, execute_generation_run_with_assets


@dataclass(frozen=True)
class GenerationWorkerSettings:
    database_url: str
    gcs_asset_bucket: str
    openai_allowed_models: tuple[str, ...]
    gcp_project_id: str | None = None
    openai_timeout_seconds: float = 180

    @classmethod
    def from_environment(cls) -> "GenerationWorkerSettings":
        models = tuple(
            model.strip()
            for model in os.getenv("OPENAI_IMAGE_ALLOWED_MODELS", "").split(",")
            if model.strip()
        )
        database_url = os.getenv("DATABASE_URL")
        bucket = os.getenv("GCS_ASSET_BUCKET")
        if not database_url or not bucket or not models:
            raise ValueError(
                "DATABASE_URL, GCS_ASSET_BUCKET, and OPENAI_IMAGE_ALLOWED_MODELS are required"
            )
        return cls(
            database_url=database_url,
            gcs_asset_bucket=bucket,
            openai_allowed_models=models,
            gcp_project_id=os.getenv("GCP_PROJECT_ID"),
            openai_timeout_seconds=float(os.getenv("OPENAI_IMAGE_TIMEOUT_SECONDS", "180")),
        )


def create_worker_app(
    settings: GenerationWorkerSettings | None = None,
    *,
    repository: PersistenceRepository | None = None,
    executor: ImageGenerationExecutor | None = None,
    object_store: PrivateObjectStore | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or GenerationWorkerSettings.from_environment()
    repository = repository or PersistenceRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    executor = executor or OpenAIImageGenerationAdapter(
        OpenAIImageProviderConfig(
            allowed_models=settings.openai_allowed_models,
            timeout_seconds=settings.openai_timeout_seconds,
        )
    )
    object_store = object_store or GcsPrivateObjectStore(
        GcsAssetStorageConfig(
            bucket_name=settings.gcs_asset_bucket,
            project_id=settings.gcp_project_id,
        )
    )
    executors = ExecutorRegistry({"openai": executor})
    app = FastAPI(title="JewelAI Generation Worker", version="1.0.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/internal/generation-tasks/execute")
    def execute(task: GenerationTaskEnvelope, response: Response):
        try:
            outcome = execute_generation_run_with_assets(
                repository,
                session_id=task.session_id,
                generation_run_id=task.generation_run_id,
                organization_id=task.organization_id,
                executors=executors,
                object_store=object_store,
                clock=clock,
            )
        except NotFoundError:
            response.status_code = 204
            return None
        return {
            "generation_run_id": str(task.generation_run_id),
            "disposition": outcome.disposition,
        }

    return app
