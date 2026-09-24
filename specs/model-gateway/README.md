# Model Gateway v1.0.0

Model Gateway v1 defines a provider-neutral, immutable boundary from one persisted `PromptRevision`
to external generation-result metadata. It does not call a provider, decide domain policy, recompile
prompts, mutate designs, or store image bytes.

`GenerationRequest` contains an exact validated `CompiledPrompt`, prompt revision identity, generation
run identity, bounded provider/model identifiers, and a bounded configuration containing only
`output_count` (1–4). It contains no raw messages, tenant identifiers, mutable designs, credentials,
provider SDK objects, or arbitrary configuration dictionaries.

`ImageGenerationGateway` is a synchronous injectable protocol. Adapter output is untrusted.
`validate_generation_result` validates the schema and requires exact generation-run, provider, model,
output-count, ordinal, and provider-output-ID integrity. Output descriptors contain metadata only and
are deliberately not called assets; JewelAI-owned asset ingestion and binary storage are deferred.
`provider_output_id` is an opaque provider identifier: it starts with an ASCII letter or digit and may
contain only ASCII letters, digits, `.`, `_`, and `-`, up to 240 characters. URLs, URIs, file paths,
data/base64 payloads, binary content, and JewelAI asset identifiers are not valid provider output IDs.

Generation lifecycle states are `pending`, `running`, `succeeded`, and `failed`, with only
pending→running and running→succeeded/failed allowed. Lifecycle timestamps are application/worker
owned. Terminal states are immutable. Retry execution is deferred; v1 records attempt 1 and supports
a nullable parent lineage field for future explicit retries.

The published [JSON Schema](schema.json) covers request, result, and persisted run read contracts.
Schema version is `1.0.0`. Test adapters prove contract and orchestration behavior only; they do not
claim provider availability, visual quality, jewelry correctness, or pixel-level lock compliance.

```sh
python -m jewelai_model_gateway.schema specs/model-gateway/schema.json
python -m pytest -c packages/model_gateway/pyproject.toml packages/model_gateway/tests -q
```
