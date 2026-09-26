# JewelAI Model Gateway

This package defines the provider-neutral Model Gateway v1 contracts. It accepts an immutable
`CompiledPrompt`, a bounded generation configuration, and explicit provider/model identifiers. It
contains no provider SDK, HTTP client, credential, persistence, FastAPI, worker, or business-rule
behavior. `GenerationExecution` and `RetrievedImageOutput` are separate transient runtime contracts;
they are not Pydantic persistence models and are excluded from the published JSON Schema.

`validate_generation_result` treats adapter results as untrusted. It requires exact run/provider/model
lineage, output count agreement, and canonical ordinal ordering before a result can be persisted as
successful. `validate_generation_execution` additionally aligns transient ordinals and provider IDs
with those descriptors. The production OpenAI adapter lives in `packages/model_gateway_openai` and
owns its timeout, response validation, and SDK dependency.

Persisted run contracts encode linear explicit retry lineage: attempt 1 has no parent, attempts above
1 require an immediate parent, and stale execution recovery is represented as terminal
`FAILED(execution_stale)` without adding another lifecycle status.

```sh
python -m jewelai_model_gateway.schema specs/model-gateway/schema.json
python -m pytest -c packages/model_gateway/pyproject.toml packages/model_gateway/tests -q
python -m ruff check packages/model_gateway
python -m ruff format --check packages/model_gateway
```
