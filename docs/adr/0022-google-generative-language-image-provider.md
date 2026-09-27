# ADR 0022: Google Generative Language image provider

- Status: Accepted for Google Gemini Image Provider v1
- Date: 2026-09-27

## Context

JewelAI has provider-neutral immutable generation contracts, an OpenAI adapter, one-shot worker
claim semantics, durable output staging, and explicit retry lineage. A second provider is needed
without coupling Google transport or credentials to domain, persistence, FastAPI, Assets, or worker
business logic. The confirmed integration target is Google's Generative Language API, not Vertex AI.

## Decision

Add `packages/model_gateway_google`, depending inward on `packages/model_gateway` and `httpx`. The
adapter sends exactly one bounded POST to
`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, authenticating
only through `x-goog-api-key`. It accepts the explicit provider ID `google` and an operator-enabled
subset of exactly `gemini-3.1-flash-lite-image`, `gemini-3.1-flash-image`, and
`gemini-3-pro-image`; it has no model or provider fallback.

V1 requires one output and sends the immutable `CompiledPrompt` with image-only response modality.
Optional image and thinking configuration is omitted because the current persisted provider-neutral
configuration does not supply deterministic values. The adapter inspects only the first candidate,
ignores text/thought parts, and requires exactly one bounded strict-base64 PNG inline part with a PNG
signature. It never fetches URLs, writes temporary files, stores raw responses, or retries HTTP.

Worker composition registers OpenAI and Google independently. Google requires its model allowlist
and runtime API key; absent Google configuration leaves existing OpenAI-only deployments unchanged.
Provider execution continues through the same claim, validation, private object staging, success,
and Asset-finalization path.

## Alternatives rejected

- Vertex AI, its SDK, or service-account authentication for Gemini model calls.
- API keys in URLs, query strings, persisted configuration, logs, exceptions, or task payloads.
- Hidden HTTP retries, multiple billable calls for requested output counts, implicit `latest`
  models, provider fallback, or silent JPEG/WebP-to-PNG relabeling.
- Google-specific fields in the jewelry schema or speculative provider-neutral fields for image
  size, aspect ratio, or thinking level.
- Recreating MyImagen text enrichment, customer-understanding logic, or image editing.

## Consequences

Google becomes a second isolated executor while canonical design and prompt state remain unchanged.
Production operators must explicitly configure allowed models and seed the API key outside Git and
Terraform state before enabling Google profiles. Unit tests use a mock HTTP transport; live model
availability, billing, quota, and output behavior remain subject to an explicit preproduction smoke
test and are not claimed by this decision.

## Validation

Contract tests cover exact request translation, header-only credential use, one-call behavior,
allowlisting, response parsing and bounds, MIME/signature enforcement, safe typed error mapping,
worker registry selection, optional Google configuration, and OpenAI regression. CI performs no
paid or live provider call.
