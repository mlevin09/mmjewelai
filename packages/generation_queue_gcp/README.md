# Google Cloud Tasks generation adapter

Publishes the minimal Generation Task v1 envelope as an authenticated HTTPS POST. Task names are
deterministic, SDK retries are disabled, and `AlreadyExists` is an idempotent success. Application
Default Credentials are used; credentials never enter configuration or payloads.
The bounded dependency is `google-cloud-tasks>=2.24,<3`; `CreateTask` uses `retry=None` and a bounded
timeout.

The worker URL must be the exact private `/internal/generation-tasks/execute` endpoint. Cloud Run IAM
must allow only the configured delivery service account to invoke the worker.
