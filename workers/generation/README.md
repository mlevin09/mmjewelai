# Generation worker boundary

`jewelai_generation.execute_generation_run` performs exactly one generation-run unit of work. It
atomically claims a pending run, loads its exact immutable prompt revision, constructs a validated
Model Gateway request, invokes one explicitly injected adapter, validates the untrusted result, and
persists success or a typed safe failure.

Duplicate delivery cannot invoke the gateway after another worker has claimed or completed the run.
Generation remains anchored to `prompt_revision_id`; a newer current specification does not
invalidate historical generation lineage.

`execute_generation_run_with_assets` is the production-capable provider-neutral path. It validates
one transient `GenerationExecution`, derives deterministic UUIDv5 Asset IDs, and stages every output
at its final private object key through the injected `PrivateObjectStore`. Only after all writes and
returned metadata verify does it persist result metadata and mark the run succeeded. It then creates
and readies Asset metadata without another storage operation.

Storage failure before success fails the run and creates no Asset rows. A crash after success can
leave Asset metadata missing, but the original bytes remain durable for future reconciliation. A
crash before staging may leave a RUNNING run, while partial staging may leave private orphan objects;
bounded timeout recovery is implemented, while reconciliation and cleanup remain future work. The
core service module imports neither OpenAI nor GCS; the separate production runtime composes those
adapters.

Production composition now delivers Cloud Tasks to the private
`POST /internal/generation-tasks/execute` endpoint, which invokes this same core path. Cloud Run IAM
must reject unauthenticated invocation. Redelivery is not a provider retry: RUNNING and terminal
duplicates, persisted provider/storage failures, and post-success materialization failures are
acknowledged without another provider call. A separate bounded timeout recovery command marks an
old RUNNING row `FAILED(execution_stale)` and never reopens it. Explicit retry then creates a new run;
Cloud Tasks redelivery never changes the business attempt.

Production composition requires `DATABASE_URL`, `GCS_ASSET_BUCKET`, and comma-separated
`OPENAI_IMAGE_ALLOWED_MODELS`; `GCP_PROJECT_ID` and `OPENAI_IMAGE_TIMEOUT_SECONDS` are optional.
The OpenAI key remains in the SDK-supported environment/secret mechanism and never enters task data.

Recovery intentionally lives at the persistence boundary and requires no worker/provider/storage
composition:

```sh
DATABASE_URL=postgresql+psycopg://... \
  python -m jewelai_persistence.recover_stale --stale-after-seconds 1800 --batch-size 100
```

```sh
python -m pytest -c workers/generation/pyproject.toml workers/generation/tests -q
python -m ruff check workers/generation
python -m ruff format --check workers/generation
```
