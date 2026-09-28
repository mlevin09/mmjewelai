# JewelAI Google Generative Language image adapter

`jewelai-model-gateway-google` is the isolated REST translation boundary for Google Gemini image
generation. It calls the Google Generative Language API—not Vertex AI—exactly once per claimed
GenerationRun:

```text
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
```

Authentication uses the runtime-only `x-goog-api-key` header. The key is never placed in the URL,
configuration representation, errors, persistence, logs, or generated artifacts. The exact initial
model set is `gemini-3.1-flash-lite-image`, `gemini-3.1-flash-image`, and
`gemini-3-pro-image`; configured models must be an explicit non-empty subset and there is no
`latest` or model fallback.

V1 requires `output_count == 1`, sends only the immutable `CompiledPrompt` text and
`responseModalities: ["IMAGE"]`, and performs no hidden HTTP retry. Optional Google
`imageConfig`/`thinkingConfig` fields are omitted because the current provider-neutral persisted
configuration does not supply them. Responses are accepted only from
`candidates[0].content.parts[].inlineData`: non-image text/thought parts are ignored, while the one
image must declare PNG, JPEG, or WebP, contain strict bounded base64, decode within the Asset limit,
and have the matching binary signature. The provider's supported media type is preserved through
the transient gateway contract and validated again by Asset ingestion. URLs, temporary files, MIME
relabeling or conversion, raw-response persistence, image editing, and text enrichment are out of
scope.

Runtime composition uses:

- `GOOGLE_GENERATIVE_LANGUAGE_API_KEY`
- `GOOGLE_GENERATIVE_LANGUAGE_ALLOWED_MODELS`
- `GOOGLE_GENERATIVE_LANGUAGE_TIMEOUT_SECONDS`

The key and allowlist are required only when Google is enabled. Operator smoke testing with an
authorized non-production key is still required before claiming live Google integration works.

```sh
python -m pytest -c packages/model_gateway_google/pyproject.toml packages/model_gateway_google/tests -q
python -m ruff check packages/model_gateway_google
python -m ruff format --check packages/model_gateway_google
```
