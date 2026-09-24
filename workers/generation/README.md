# Generation worker boundary

`jewelai_generation.execute_generation_run` performs exactly one generation-run unit of work. It
atomically claims a pending run, loads its exact immutable prompt revision, constructs a validated
Model Gateway request, invokes one explicitly injected adapter, validates the untrusted result, and
persists success or a typed safe failure.

Duplicate delivery cannot invoke the gateway after another worker has claimed or completed the run.
Generation remains anchored to `prompt_revision_id`; a newer current specification does not
invalidate historical generation lineage. No queue polling, retry loop, provider adapter, image
storage, asset ingestion, or deployment behavior exists here.

```sh
python -m pytest -c workers/generation/pyproject.toml workers/generation/tests -q
python -m ruff check workers/generation
python -m ruff format --check workers/generation
```
