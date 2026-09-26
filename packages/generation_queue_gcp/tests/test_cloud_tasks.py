from uuid import UUID

import pytest
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable
from jewelai_generation_queue import GenerationTaskEnvelope, GenerationTaskPublishUnavailableError
from pydantic import ValidationError

from jewelai_generation_queue_gcp import (
    CloudTasksGenerationConfig,
    CloudTasksGenerationPublisher,
)


class Client:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def queue_path(self, project, location, queue):
        return f"projects/{project}/locations/{location}/queues/{queue}"

    def create_task(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error


def config(**updates):
    values = dict(
        project_id="jewelai-prod",
        location="us-central1",
        queue_id="generation",
        worker_task_url="https://worker.example.test/internal/generation-tasks/execute",
        oidc_service_account_email="tasker@jewelai-prod.iam.gserviceaccount.com",
        oidc_audience="https://worker.example.test",
        api_timeout_seconds=4,
    )
    values.update(updates)
    return CloudTasksGenerationConfig(**values)


def envelope():
    return GenerationTaskEnvelope(
        generation_run_id=UUID("11111111-1111-4111-8111-111111111111"),
        session_id=UUID("22222222-2222-4222-8222-222222222222"),
        organization_id=UUID("33333333-3333-4333-8333-333333333333"),
    )


def test_exact_cloud_task_request():
    client = Client()
    result = CloudTasksGenerationPublisher(config(), client=client).publish(envelope())
    call = client.calls[0]
    task = call["request"]["task"]
    assert (
        call["request"]["parent"] == "projects/jewelai-prod/locations/us-central1/queues/generation"
    )
    assert task.name.endswith("/tasks/generation-11111111111141118111111111111111")
    assert task.http_request.url == config().worker_task_url
    assert task.http_request.body == envelope().model_dump_json().encode()
    assert task.http_request.headers["Content-Type"] == "application/json"
    assert task.http_request.oidc_token.service_account_email == config().oidc_service_account_email
    assert task.http_request.oidc_token.audience == config().oidc_audience
    assert call["retry"] is None and call["timeout"] == 4
    assert result.task_id.startswith("generation-")


def test_already_exists_is_success_and_other_google_errors_are_safe():
    CloudTasksGenerationPublisher(config(), client=Client(AlreadyExists("duplicate"))).publish(
        envelope()
    )
    with pytest.raises(GenerationTaskPublishUnavailableError) as caught:
        CloudTasksGenerationPublisher(
            config(), client=Client(ServiceUnavailable("secret queue"))
        ).publish(envelope())
    assert "secret queue" not in str(caught.value)


@pytest.mark.parametrize(
    "updates",
    [
        {"project_id": "bad/project"},
        {"location": " BAD"},
        {"queue_id": "bad_queue"},
        {"worker_task_url": "http://worker.test/internal/generation-tasks/execute"},
        {"worker_task_url": "https://user@worker.test/internal/generation-tasks/execute"},
        {"worker_task_url": "https://worker.test /internal/generation-tasks/execute"},
        {"worker_task_url": "https://worker.test/other"},
        {"worker_task_url": "https://worker.test/internal/generation-tasks/execute#x"},
        {"oidc_service_account_email": "not-an-email"},
        {"oidc_audience": "http://worker.test"},
        {"oidc_audience": "https://worker.test /audience"},
    ],
)
def test_invalid_server_configuration_fails_closed(updates):
    with pytest.raises(ValidationError):
        config(**updates)
