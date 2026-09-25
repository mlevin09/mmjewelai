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
recovery and cleanup remain future work. The worker imports neither OpenAI nor GCS.

```sh
python -m pytest -c workers/generation/pyproject.toml workers/generation/tests -q
python -m ruff check workers/generation
python -m ruff format --check workers/generation
```
