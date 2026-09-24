# JewelAI Model Gateway

This package defines the provider-neutral Model Gateway v1 contracts. It accepts an immutable
`CompiledPrompt`, a bounded generation configuration, and explicit provider/model identifiers. It
contains no provider SDK, HTTP client, credential, persistence, FastAPI, worker, image bytes, or
business-rule behavior.

`validate_generation_result` treats adapter results as untrusted. It requires exact run/provider/model
lineage, output count agreement, and canonical ordinal ordering before a result can be persisted as
successful. Real adapters must enforce their own bounded network timeouts; none are implemented in
v1. Deterministic fake adapters live only in tests.

```sh
python -m jewelai_model_gateway.schema specs/model-gateway/schema.json
python -m pytest -c packages/model_gateway/pyproject.toml packages/model_gateway/tests -q
python -m ruff check packages/model_gateway
python -m ruff format --check packages/model_gateway
```
