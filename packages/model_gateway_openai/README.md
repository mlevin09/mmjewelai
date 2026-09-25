# JewelAI OpenAI image adapter

`jewelai-model-gateway-openai` is the sole OpenAI SDK boundary. It translates one immutable
provider-neutral `GenerationRequest` into one synchronous `client.images.generate(...)` call and
returns metadata plus transient decoded PNG bytes. It does not import FastAPI, persistence, Assets,
GCS, or the generation worker.

The production client uses standard `OPENAI_API_KEY` environment credential discovery, a bounded
180-second default timeout, and `max_retries=0` because generation is potentially billable and v1
has no durable provider-call idempotency strategy. Configuration contains only an allowlist of exact
server-selected model IDs, timeout, and a maximum output size capped at the Asset limit; it contains
no credentials.

OpenAI GPT Image output is read only from `b64_json`, bounded before allocation, decoded with strict
base64 validation, and kept in the transient `GenerationExecution`. The adapter requests PNG and
never fetches provider URLs. `GenerationResult` remains metadata-only.

The verified initial model snapshot is `gpt-image-2.5-sunburst-2026-09-08`, used through the
dedicated Images API generation method. A manual paid smoke test may be composed explicitly with
`OPENAI_API_KEY`; it is not part of CI or application startup.

```sh
python -m pip install -e './packages/model_gateway_openai[test]'
python -m pytest -c packages/model_gateway_openai/pyproject.toml packages/model_gateway_openai/tests -q
python -m ruff check packages/model_gateway_openai
python -m ruff format --check packages/model_gateway_openai
```
