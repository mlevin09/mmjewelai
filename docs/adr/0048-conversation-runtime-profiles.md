# ADR 0048 — Configurable conversation runtimes and bounded operational evidence

EN MASTER · 2026-11-20 · Issue #191 · implementation for independent review.
Not activation, professional qualification, deployment or functional acceptance.

## Context and decision

[ADR 0047](0047-us01-dual-interpretation-commit-aware-reply.md) remains authoritative:
original text independently reaches model and Parser; SO/Matrix alone authorizes State;
after commit the model proposes a reply which must pass the existing factual validator.
HTTP 200 and a configured model do not establish correct interpretation or delivery.

Reuse `ConversationModel`, `QwenConversationConfig` and the existing llama.cpp adapter.
A startup-only registry composes that adapter from explicitly selected approved profiles.
No second conversational core, Parser, State, experiment controller or provider service.

- `ST01_CONVERSATION_PROFILES_JSON`: array of up to 16 named configurations.
- `ST01_CONVERSATION_ACTIVE_PROFILE`: exact profile ID, or `disabled`.
- A profile requires `profile_id`, `engine=llama_cpp`, `approved` (boolean), exact
  private `endpoint`, `model`, `model_sha256`, `runtime_build`, and `context_tokens`.
  The dataclass also validates sampling, timeout, output bounds, no streaming and
  exactly one attempt. Unknown keys, duplicate JSON keys/IDs and unapproved or
  missing selection fail startup. Approval is an operator declaration, not model attestation.
- Anonymous named profiles are limited to loopback. Remote profiles require HTTPS
  plus `bearer_env` (secret environment reference, never inline) or `google_id_token`
  with the exact HTTPS origin audience. Tokens stay server-side; no redirects/retries.
  This does not create a certificate, gateway, VPC route, IAM grant or secret.
- Existing legacy `ST01_CONVERSATION_PROVIDER=qwen` remains backward-compatible.
  Mixing it with a named active profile is rejected. Explicit `disabled` wins.
- Preprod reads checked-in `infra/terraform/preprod/conversation.json` into these two
  environment variables. It is **disabled with an empty registry**. A future reviewed
  configuration-only deployment can select A, B, then A without business-code edits.
  Production files and provider-generation profiles are unchanged.

The existing flexible `model_runtime`/`sampling` receipt carries profile, engine,
model/artifact/build, inference settings and endpoint hash. No new durable table,
DTO, public route or schema version. Delivered historical receipts use their retained
provider/model, not the currently selected configuration. A pending turn refuses a
changed runtime with the existing 409 conflict before another reply call. Reads and
idempotent replay do not invoke inference. Existing source/State/hash validation stays.

Numeric phase logs contain message identity, selected model/pins/configuration hash,
untrusted draft outcome or bounded error code and latency. They contain no text,
headers, raw exceptions, response bodies or credentials. A generated draft is never
logged as an accepted State update or verified model reply.

## Model evidence and instructions

Actual saved model replies were rejected by `checked_reply()`:
RU omitted committed critical facts; EN's unqualified sapphire statement failed the
uncommitted-fact guard. Both also failed to resolve the source quantity scope.
Model interpretations supplied invalid metal values/quotes, so SO correctly withheld
metal facts. A bounded stronger-instruction experiment still produced invalid source spans and false
saved claims, with worse latency (RU 104.516s, EN 94.821s). It is not retained in the final
patch. Existing instructions, validator and SO remain unchanged. These model-quality
failures are not repaired by configuration or HTTP success; they remain explicit
blockers, with honest fallback and unchanged history.

The lab boot configuration loads Qwen3-1.7B, context 2048, two threads, reasoning budget
zero. The separately observed Qwen3-4B process had context 4096; its research installation
is not a silently promoted boot default or product-qualified profile. No model or
systemd configuration is changed here. Operator IAP/SSH access is not an API data plane.

## Speech latency

Existing Cloud Run evidence and four real authenticated synthetic-audio requests show
cold startup dominates the first request; warm inference is much faster. The existing
public proxy deliberately strips internal `processing_ms`. Add private numeric
`audio_read_ms`, `auth_ms`, `upstream_ms`, bounded internal `processing_ms`, total and
outcome/request identity. Audio read timing begins after multipart parsing; it is not
browser recording/upload timing. Invalid optional timing never changes the public
three-field editable-text response. No audio, transcript, tokens or URLs are logged.

Reduce preprod startup probe period/timeout to 1 second, threshold 240, retaining the
same 240-second startup allowance and model-readiness check. Min0/max1, CPU/memory,
image digest, offline network and IAM stay unchanged. This removes up to nine seconds
of *possible probe polling delay*, not model loading. No warm instance/CPU boost/GPU.
Reference: [Cloud Run probe semantics](https://docs.cloud.google.com/run/docs/configuring/healthchecks).
No after-deployment improvement is claimed without an authorized deployment/measurement.

## Remaining material gate and alternatives

The API uses `jewelai-preprod-stt-caller`; the VM is on `default`, and llama.cpp binds
localhost without caller authentication. Pointing the API at the VM IP cannot establish
a secure inference route. Do not expose localhost serving publicly or grant compute
administration/SSH authority to the API as a shortcut.

One infrastructure decision is required before activation: approve a reviewed private
HTTPS inference-only gateway on this existing VM, a scoped route from the API caller
network, TLS identity, and authorization limited to the API service identity. No VM
lifecycle/guest execution tools in the API. Concrete least-privilege plan and certificate
mechanism must be reviewed before any shared network/IAM/deployment change. Current
code supports the caller authentication boundary but deploys none of that infrastructure.

Keep disabled until a qualified runtime and safe route are verified. The 60-second API
request deadline also must be respected; increasing it alone is not a latency fix.
An anonymous private listener, public gateway, broad IAM, min1 STT and replacing the
model without qualification were rejected alternatives. Full Regression remains a
separate Owner gate; exact-head targeted CI is not independent functional acceptance.
