"""Google Cloud Tasks implementation of the generation publisher port."""

import re
from typing import Any
from urllib.parse import urlsplit

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError
from google.cloud import tasks_v2
from jewelai_generation_queue import (
    GenerationTaskEnvelope,
    GenerationTaskPublishUnavailableError,
    PublishedGenerationTask,
    generation_task_id,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

_RESOURCE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_SERVICE_ACCOUNT = re.compile(
    r"^[a-z0-9][a-z0-9-]{4,62}[a-z0-9]@"
    r"[a-z][a-z0-9-]{4,61}[a-z0-9]\.iam\.gserviceaccount\.com$"
)


class CloudTasksGenerationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    location: str
    queue_id: str
    worker_task_url: str = Field(max_length=2048)
    oidc_service_account_email: str = Field(max_length=320)
    oidc_audience: str = Field(max_length=2048)
    api_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    @field_validator("project_id", "location", "queue_id")
    @classmethod
    def resource_component(cls, value: str) -> str:
        if value != value.strip() or not _RESOURCE.fullmatch(value):
            raise ValueError("Cloud Tasks resource component is invalid")
        return value

    @field_validator("oidc_service_account_email")
    @classmethod
    def service_account(cls, value: str) -> str:
        if value != value.strip() or not _SERVICE_ACCOUNT.fullmatch(value):
            raise ValueError("Cloud Tasks service account identity is invalid")
        return value

    @field_validator("worker_task_url")
    @classmethod
    def worker_url(cls, value: str) -> str:
        cls._validate_https_url(value, exact_path="/internal/generation-tasks/execute")
        return value

    @field_validator("oidc_audience")
    @classmethod
    def audience(cls, value: str) -> str:
        cls._validate_https_url(value)
        return value

    @staticmethod
    def _validate_https_url(value: str, exact_path: str | None = None) -> None:
        parsed = urlsplit(value)
        if (
            value != value.strip()
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
            or (exact_path is not None and parsed.path != exact_path)
        ):
            raise ValueError("Cloud Tasks URL must be an exact absolute HTTPS URL")


class CloudTasksGenerationPublisher:
    def __init__(
        self,
        config: CloudTasksGenerationConfig,
        *,
        client: Any | None = None,
    ):
        self.config = CloudTasksGenerationConfig.model_validate(config)
        self._client = client or tasks_v2.CloudTasksClient()

    def publish(self, task: GenerationTaskEnvelope) -> PublishedGenerationTask:
        task = GenerationTaskEnvelope.model_validate(task)
        task_id = generation_task_id(task.generation_run_id)
        parent = self._client.queue_path(
            self.config.project_id, self.config.location, self.config.queue_id
        )
        cloud_task = tasks_v2.Task(
            name=f"{parent}/tasks/{task_id}",
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=self.config.worker_task_url,
                headers={"Content-Type": "application/json"},
                body=task.model_dump_json().encode("utf-8"),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self.config.oidc_service_account_email,
                    audience=self.config.oidc_audience,
                ),
            ),
        )
        try:
            self._client.create_task(
                request={"parent": parent, "task": cloud_task},
                retry=None,
                timeout=self.config.api_timeout_seconds,
            )
        except AlreadyExists:
            pass
        except GoogleAPICallError as exc:
            raise GenerationTaskPublishUnavailableError(
                "Generation task publication is unavailable"
            ) from exc
        return PublishedGenerationTask(task_id=task_id)
