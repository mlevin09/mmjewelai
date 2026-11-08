# Private self-hosted STT v1

Status: implementation for independent review; **not built into an image, installed on GPU,
deployed, or speech-accuracy qualified**. The developer host has no Docker engine or GPU.
This service has no Parser, Knowledge, database, Asset or Product State dependency.

## Internal contract

`POST /internal/v1/transcriptions?language=ru|en` accepts **raw binary**, not JSON/multipart,
under `Content-Type: audio/wav`, `audio/webm` (Opus), or `audio/ogg` (Opus).
The hint is optional. Remote audio URLs, caller-selected destinations and other query parameters
are rejected. MP4/M4A, streaming and Hebrew are not supported in this slice.

Cloud Run ingress is INTERNAL_ONLY; invoker IAM checking remains enabled. Only the existing API
service account is granted `roles/run.invoker` on this service. The server-side client obtains a
Google ID token through ADC/metadata, with the **exact service origin as audience**. No key JSON,
shared bearer secret, external JWKS fetch in the STT container or browser access is required.
Platform IAM is the authentication boundary: running uvicorn alone is NOT an authenticated service.
Do not expose this container directly outside the controlled Cloud Run configuration.

Example response (synthetic text):

```json
{
  "schema_version": "1.0.0",
  "status": "transcribed",
  "text": "I want a ring.",
  "language": "en",
  "duration_ms": 4200,
  "processing_ms": 900,
  "model": "Qwen/Qwen3-ASR-1.7B",
  "model_revision": "7278e1e70fe206f11671096ffdd38061171dd6e5"
}
```

Digital/near-digital silence returns 200, `status=silence`, empty text and null language without
inference. This is not a general VAD or a guarantee against hallucinations on noisy/non-speech audio.
The user must be able to review/edit the transcript before submitting it to the existing text flow.

Safe errors use `{"error":{"code":"…"}}`: invalid request 400; unsupported language/audio 422/415;
byte/duration limit 413; upload timeout 408; busy 429; decode/inference timeout 504;
model unavailable 503. No upstream body or exception string is returned. Cloud Run may return its
own 401/403 before the application. The client redacts those as `stt_access_denied`.

Limits: 10 MiB compressed input; 60 s decoded audio; mono 16 kHz float32 output; 8 s wall-clock
decode limit; Linux decoder address-space limit 768 MiB / CPU limit 6 s; 40 s inference deadline;
10 s upload deadline; one request at a time; 8192 output characters. Decoder accepts only pipe
protocol and an explicit container format. No temporary audio files are used. Timeout terminates
the model process and makes health fail, allowing Cloud Run liveness to replace the instance.
Buffers are released after use, not cryptographically erased from memory. No audio/transcript
logging, storage, upload to GCS or automatic Message/revision creation occurs.

`GET /health` is 200 only after model initialization, otherwise 503. Cloud Run startup budget is
240 s. Readiness, cold-start duration, GPU peaks and CUDA driver compatibility require real GPU
qualification; passing fake-engine tests is not that qualification.

## Reproducible build

* Python base: 3.12.14 slim-bookworm, linux/amd64 manifest
  `sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a`.
* Model: `Qwen/Qwen3-ASR-1.7B`, revision above, Apache-2.0.
* `qwen-asr==0.0.6`, `transformers==4.57.6`, `accelerate==1.12.0`,
  `torch==2.10.0+cu126`, `numpy==2.2.6`; full transitive hashes in `requirements-linux.lock`.
* CUDA wheel is a direct hash-pinned official PyTorch URL. No vLLM or ForcedAligner.
* Qwen's package declares demo dependencies; they are locked but no demo/Gradio/Flask server runs.
* `imageio-ffmpeg==0.6.0` supplies the local decoder binary. New dependencies belong only to STT.

Model weight SHA-256 values, verified against official Hugging Face metadata:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| model-00001-of-00002.safetensors | 4220320824 | a4cd1f1a04d90b757dc7f7dd26254e69a013b19e80efe590a83c6a3bde8608d6 |
| model-00002-of-00002.safetensors | 478200688 | 6e0b9d9e09e2e0238e7ef3cc8a484ab387e91b90f1900bedf88bc92d7929ccfc |

The network-enabled **build** stage acquires only the exact snapshot, checks both known weight
hashes and produces `/opt/model/manifest.json` binding every copied artifact. Startup verifies that
manifest and weight hashes before loading a local directory with `local_files_only=True`. The image
digest binds the manifest itself. Missing/tampered/unexpected files fail closed. Offline environment
flags disable hub access and telemetry; they supplement network isolation, never replace it.

On an approved Linux/amd64 Docker build host:

```sh
docker build --platform linux/amd64 -f infra/docker/stt.Dockerfile -t jewelai-stt:review .
```

Do not use this command as a claim that a build occurred. Before approval/promotion, retain build
logs, manifest bytes/SHA-256, dependency lock SHA-256, image digest and license notices. The complete
model manifest and STT image digest do not yet exist in this delivery. No model weights are in Git.
Do not upload the large image, configure activation variables or provision resources before the
resource/cost gate. Offline startup must later be exercised with a locally loaded image under
`--network=none --gpus all`, followed by cloud-network qualification.

Lock regeneration uses uv 0.9.5 (metadata resolution, not inference):

```sh
uv pip compile apps/stt/pyproject.toml --extra model --extra build \
  --python-version 3.12 --python-platform x86_64-unknown-linux-gnu \
  --generate-hashes --no-annotate --output-file apps/stt/requirements-linux.lock
uv pip compile apps/stt/build-requirements.in --generate-hashes --no-annotate \
  --output-file apps/stt/requirements-build.lock
```

The initial Linux/CUDA dependency graph was resolved against the explicit official cu126 index;
its Torch entry was then narrowed to the exact official cp312/Linux wheel URL/hash. Resolving a
direct wheel again can download that 803 MiB wheel just for metadata; one such redundant local
resolution was stopped. No model weights or GPU inference were involved. Build-tool hashes are
separate so source-only Python dependencies build without unpinned build-isolation downloads.

## Preproduction configuration and cost gate

`infra/terraform/preprod/stt.tf` is part of the existing preprod state, not a new independently
applied stack. Empty `stt_image` (default) creates **zero STT resources** and adds no API VPC block.
Activation also requires non-empty `stt_resource_approval_reference`; it records Owner approval,
not automatic authorization. No GitHub variables were changed by implementation.

The existing preprod workflow reads optional `STT_IMAGE` and `STT_RESOURCE_APPROVAL_REFERENCE` and
binds both into the plan/apply configuration fingerprint. Exact SHA, WIF, saved binary plan,
checksum/object-generation checks and apply-without-replanning remain in place. There is no new
deployment trigger or automatic model build/download in CI. No production workflow/config changes.

Proposed resources after explicit approval:

* One Cloud Run L4 (24 GB VRAM), 4 vCPU, 16 GiB RAM, min 0 / max 1 / concurrency 1,
  instance billing, zonal redundancy off; no VM, NAT, connector, PSC or Load Balancer.
* Caller VPC/subnet with Private Google Access and private `*.run.app` DNS pointing at
  `199.36.153.4/30`; API uses PRIVATE_RANGES_ONLY Direct VPC. This follows Google's documented
  direct internal Cloud Run route and preserves API's other Internet calls.
* Separate inference VPC/subnet, IPV4_ONLY, no Private Google Access; STT uses ALL_TRAFFIC
  Direct VPC, network tag with deny-all IPv4/IPv6 egress and DNS response-policy wildcard sink.
  Separate networks prevent the inference DNS sink from breaking the API's external calls.
* Runtime SA with no new project roles, secret grants or database/Asset access; invoker IAM
  bound only to API identity. Cloud Run service agent handles image acquisition separately.

Default run.app DNS hostname exists and is required for this route; it is **not publicly callable**
when ingress and IAM are enforced. It is not a private-IP endpoint. Platform request/response
handling, metadata, DNS, image pull and logging are distinct from container Internet egress.
Metadata access cannot be claimed blocked by VPC firewall; no model credentials are needed there.
The STT container does not send payloads to platform logging. Network claims remain NOT TESTED
until the live negative tests below pass, including DNS types other than A/AAAA.

2026-11-08 read-only quota check: no GPU Cloud Run service exists; Cloud Run L4 quota buckets did
not return a positive effective allocation; Compute Engine GPUS_ALL_REGIONS=0. Regional Compute
L4 quota=1 from preflight is not a usable global GPU grant. Cloud Run and Compute quotas differ.
Google documents initial non-redundant Cloud Run quota auto-grant at first deploy; capacity/quota
must be checked then, without substituting GCE or changing region silently.

USD planning rate (public on-demand table, confirm Belgium billing SKU before spend):
`3600 * (0.0001867 + 4*0.000018 + 16*0.000002) = $1.04652/allocated instance-hour`.
100 allocated hours ≈ $104.65; 730 h ≈ $763.96. Startup and idle-before-scale-down count; these are
not audio-hours. Private DNS zone adds about $0.20/month plus queries; registry/build/log storage
adds usage costs (image size not measured). No recurring paid gateway is introduced. Pricing:
[Cloud Run](https://cloud.google.com/run/pricing), [Cloud DNS](https://cloud.google.com/dns/pricing).

## Required installation evidence (NOT TESTED)

After independent review and explicit resource approval, use the existing audited preprod
deployment-request flow with the pinned STT image. Inspect the saved plan before apply. Do not
deploy this task automatically. Keep the text-only flow independent of STT failure.

1. Confirm positive L4 quota/capacity, correct image/manifest and GPU startup/readiness.
2. Synthetic real RU/EN clips → manually checked transcript; silence, invalid, overlong/oversized
   input and model timeout; audio must not appear in logs or durable storage.
3. Public caller denied with and without a valid credential; internal unauthorized identity denied;
   API identity accepted. Local ASGI tests cannot prove platform IAM/network behavior.
4. From the exact inference revision/network, test blocked external HTTPS, direct IPv4, IPv6,
   external DNS/DoH/alternate DNS, and A/AAAA/TXT random-name resolution. Confirm the DNS sink does
   not forward random names. Preserve sanitized outcome/status only. No customer audio.
5. Cold start and inference with Internet blocked; no hub/model downloads or telemetry; measure
   wall time, peak GPU/RAM and readiness against the configured bounds.
6. Confirm existing API provider calls still work through the caller DNS/routing change.

Any failed isolation check blocks exposure/integration. Rollback uses the previous reviewed image
digest and saved-plan process; failed model startup leaves STT unhealthy. Do not simply empty the
image variable to delete resources: deletion protection intentionally requires reviewed retirement.

## Frontend handoff / exact pending contract decision

The browser must never call the run.app STT endpoint or receive a service credential. The reusable
`jewelai_stt.client.SttClient` is server-only and deliberately not installed/wired into the public API.

Owner/coordinator decision package for the next integration: authorize a tenant/session-scoped
browser-facing transcription endpoint, accepted WAV/WebM/OGG limits, transient-audio/no-durable-audio
retention, and user transcript review/edit before existing Message submission. Suggested route:
`POST /v1/sessions/{session_id}/transcriptions`, with existing organization/session authorization
resolved **before** reading bytes. This route is a proposal, not implemented or approved here.
No canonical changes, automatic decisions, audio Asset type or new persisted provenance type is
needed for this internal slice. ChatGPT owns microphone/UI work and subsequent integration review.

## Focused developer validation

```sh
python3 -m pip install './apps/stt[test]'
python3 -m pytest -c apps/stt/pyproject.toml apps/stt/tests -q
python3 -m ruff check apps/stt
python3 -m ruff format --check apps/stt
terraform fmt -check infra/terraform/preprod/stt.tf infra/terraform/preprod/services.tf
python3 infra/terraform/check_invariants.py
git diff --check
```

Model extra is unnecessary for normal tests. Codec tests use real FFmpeg and synthetic waveforms;
RU/EN HTTP tests use a fake recognizer. macOS codec tests do not qualify Linux RLIMIT_AS. Cloud
tests above are NOT TESTED and must never be inferred from unit-test PASS. No Full Regression.
