# Infrastructure

Reserved for JewelAI V2 deployment and infrastructure-as-code artifacts.

No cloud resources are provisioned in Step 2. Future infrastructure work must follow the accepted platform direction and subsequent ADRs for authentication/tenancy, durable queues, persistence, assets, secrets, and deployment.

Never commit credentials, customer assets, or environment secrets here.

Durable generation deployment requires a Cloud Tasks queue, private generation Cloud Run service,
task-delivery OIDC service account, least-privilege IAM bindings, finite retry/backoff plus dispatch
rate/concurrency configuration, and an operational bounded outbox-redrive invocation. The API runtime
may create tasks and use the delivery identity; that identity may invoke only the worker; the worker
has only its database, private GCS, and OpenAI runtime access. Never make the worker public or grant
project-wide Owner/Editor or broad Storage Admin roles. These resources are not provisioned here.

Operations must also invoke the bounded stale-recovery command, eventually through a private Cloud
Run Job/Scheduler arrangement. This repository does not provision that job. Recovery uses only
PostgreSQL, marks old RUNNING rows failed, and never calls the provider or creates retries.
