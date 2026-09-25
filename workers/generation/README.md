# Generation worker boundary

`jewelai_generation.execute_generation_run` performs exactly one generation-run unit of work. It
atomically claims a pending run, loads its exact immutable prompt revision, constructs a validated
Model Gateway request, invokes one explicitly injected adapter, validates the untrusted result, and
persists success or a typed safe failure.

Duplicate delivery cannot invoke the gateway after another worker has claimed or completed the run.
Generation remains anchored to `prompt_revision_id`; a newer current specification does not
invalidate historical generation lineage.

`execute_generation_run_with_assets` is the production-capable provider-neutral path. It validates
one transient `GenerationExecution`, checks PNG content before run completion, persists only result
metadata, then uses existing Asset ingestion with an injected `PrivateObjectStore`. Generated Asset
IDs are deterministic UUIDv5 values from a fixed namespace plus `{generation_run_id}:{ordinal}`.
Storage failure leaves the run succeeded and the Asset failed. A crash can leave a succeeded run
without its Asset; reconciliation, queue delivery, and automatic retries remain separate future
work. The worker imports neither OpenAI nor GCS.

```sh
python -m pytest -c workers/generation/pyproject.toml workers/generation/tests -q
python -m ruff check workers/generation
python -m ruff format --check workers/generation
```
