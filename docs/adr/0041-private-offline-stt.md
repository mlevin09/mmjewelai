# ADR 0041: Private offline speech transcription before existing text intake

Status: Private path qualified 2026-11-09; GPU disabled by Owner decision; CPU replacement proposed.
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

## 2026-11-09 live qualification correction (pending deployment)

Owner authorized the agreed GPU/build/storage costs and actual preprod installation. The pinned
image was built and verified offline, and revision `jewelai-preprod-stt-00001-xrr` became Ready
through audited deployment run `42531993325`, source `6d6e61e09d93bcbe2d44686d729533711c283345`.
This is installation evidence, not successful speech or Studio qualification.

An operational probe using the exact STT digest, identity, VPC and firewall tags confirmed that
A/AAAA resolve to loopback and direct IPv4/IPv6/UDP DNS egress is blocked. However, known public
TXT and MX records remained resolvable: the response policy does not stop fallback for RR types
without local data. The original random-name TXT NXDOMAIN check was insufficient because public
recursion can return the same negative result. Keep that failed evidence; use known-positive
public TXT/MX controls in subsequent live checks. No audio was submitted after this failed gate.

Add one authoritative, empty private root zone (`.`) visible **only** to the inference VPC.
Retain the existing A/AAAA policy, workload firewall and separate caller DNS. Missing name/type
answers must terminate locally rather than use public recursion. This is an additive correction
to the approved no-runtime-DNS requirement, with no gateway, NAT, DNS forwarder or new public API.
The API/caller network must never be attached to the root zone. Google documents that private
zones terminate absent-name resolution and warns that root/catch-all private DNS overrides all
names; that is intentional only for the isolated offline inference network.

The new zone is not yet deployed or live-qualified. Retest TXT/MX positive controls, random names,
A/AAAA, external DNS/HTTPS/IP reachability and actual model startup/inference before enabling user
speech. Platform metadata, image-pull, logging and response channels remain separately scoped.
See [Cloud DNS resolution order](https://docs.cloud.google.com/dns/docs/vpc-name-res-order).

## 2026-11-09 Owner decision: separate CPU-only STT

After real RU/EN inference and isolation qualification on deployment
`e3ceb499c65df239e7fd20f9d4685e6dcef1d820`, Owner rejected GPU cost for this feature,
including GPU scale-to-zero as the long-term solution. The GPU service was explicitly placed
in manual scaling zero; voice is temporarily unavailable and typed input remains available.
Earlier GPU/DNS status above is historical evidence, not current activation guidance.

Replace the executable Qwen/Torch/CUDA model path with pinned multilingual Whisper Small INT8
through faster-whisper/CTranslate2, on a separate 2 vCPU/2 GiB service, request billing, min zero,
max one. Keep the existing internal byte/text contract, private IAM/routing, offline artifacts,
no audio persistence, editable transcript and explicit Submit. No Parser, text LLM, Product State,
provider adapters or production configuration changes. Narrow spelling hints and local bundled VAD
are ASR aids, never accepted jewelry requirements or post-recognition substitutions.

Alternatives measured: Qwen0.6B FP32 needed approximately 6 GiB RAM; Whisper Base was faster but
missed oval terminology. Unmodified Small still missed prong/pear terms. Consequently promotion
requires real original-fixture and independent negative/no-speech qualification, not mocked tests.
A second CPU ASR process on the API would compete with its request handling and authority runtime;
retain independent sizing and lifecycle. Future resource sharing can be separately evaluated.

The existing Terraform service removes GPU resources/selectors and explicitly restores automatic
min-zero scaling only with the reviewed CPU image. Review and coordinator-controlled preprod
deployment remain gates; the previous GPU image must not be reactivated. No permanent warm CPU
instance is approved by this change. Cold-start delay and synthetic-to-human accuracy remain risks.
See [current STT implementation and handoff](../../apps/stt/README.md) for pins and qualification.

Sources: [faster-whisper CPU/VAD usage](https://github.com/SYSTRAN/faster-whisper),
[pinned decoding API](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py).

## PR #175 release-safety correction

Automatic CPU scaling is conditional on a code-reviewed immutable CPU image allowlist and the
exact digest-bound CPU resource approval supplied together. Historical GPU variables, mixed
pairs and missing approval fail Terraform variable validation before apply. Routine unrelated
preprod deployments therefore cannot clear the operational manual-zero hold. Updating the CPU
allowlist requires review; this is not a new secret or IAM authority. The existing saved-plan,
configuration fingerprint, WIF and Environment controls remain authoritative. See the
[release handoff](../operations/stt-cpu-release-pr175.md) for image, tests and coordinator gates.


The transition is two-phase: digest-bound `cpu-stage:` approval changes the template while
preserving MANUAL/count0; `cpu-only:` activation is rejected unless a live service read proves
that exact CPU image,2CPU/2GiB/request billing and no accelerator are already latest-created=Ready.
This avoids enabling service-wide autoscaling while the previous GPU revision might still be
serving. Both phases use the existing deployment inputs and exact-plan process, without workflow
changes or automatic GPU rollback.
