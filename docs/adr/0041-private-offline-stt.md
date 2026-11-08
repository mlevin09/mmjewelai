# ADR 0041: Private offline speech transcription before existing text intake

Status: Proposed implementation of Owner-approved STT boundaries; resource activation pending.
Date: 2026-11-08.

## Context

Owner approved self-hosted Qwen3-ASR first, with no external transcription API, public callable
inference endpoint, runtime Internet, paid gateway or changes to text understanding authority.
Existing API and image worker need their external calls and must not inherit an STT egress ban.
Browser-facing ingestion/privacy semantics remain a separate explicit approval boundary.

## Decision

Add a standalone, ephemeral internal STT service with a versioned byte-input/text-output contract.
Use a revision/hash-bound local model bundle and pinned Python/CUDA dependencies; build acquires
artifacts, startup/inference never downloads them. Decode untrusted audio with protocol/container,
size, time, CPU and Linux address-space bounds; terminate a timed-out model process. Log no payload.

Prepare an optional preprod Cloud Run L4 service, disabled by default. Internal ingress plus
platform IAM authorizes only the existing API identity. Retain run.app for Google's documented
direct invocation route: caller Direct VPC + Private Google Access + restricted-VIP DNS. A separate
inference VPC supplies deny-all workload egress and a DNS sink without breaking API external calls.
No Load Balancer, NAT, connector, PSC, VM, API route, migration or database writes are introduced.
Activation requires explicit resource/cost approval, an immutable image and the existing exact-plan
deployment controls. Production is untouched. No live isolation or GPU accuracy claim is made.

## Alternatives

* Internal Load Balancer/private-IP ingress: rejected by Owner for recurring gateway cost.
* IAM alone or offline environment flags alone: insufficient network/egress isolation.
* One DNS-sink VPC shared with the API: would disrupt existing API calls.
* GCE: additional operations and currently blocked by global GPU quota; not an automatic fallback.
* External STT API or a self-hosted LLM: outside approved boundaries.

## Consequences and approval gates

Cold starts, actual GPU memory and Torch/CUDA compatibility require GPU qualification. Platform
channels (metadata, DNS, image pull, logging and response routing) are not ordinary container
egress and must be tested/documented separately. Internal ingress does not create a private IP.
Wildcard DNS sink behavior, including non-A/AAAA lookups, is a mandatory live gate.

Transcription remains untrusted editable text; it cannot create canonical facts, decisions or
Messages automatically. A public tenant/session-scoped audio endpoint, retention policy and Studio
integration require the precise Owner/coordinator decision described in
[STT handoff](../../apps/stt/README.md). Existing Parser, provenance, KEEP/LOCK and history remain
unchanged. Container and Terraform recipes are not evidence of deployment or successful inference.

Sources: [private Cloud Run routing](https://docs.cloud.google.com/run/docs/securing/private-networking),
[Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc),
[IAM](https://docs.cloud.google.com/run/docs/authenticating/service-to-service),
[Qwen runtime](https://github.com/QwenLM/Qwen3-ASR).
