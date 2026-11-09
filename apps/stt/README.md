# Private CPU speech transcription

## Current state and scope

Owner chose a separate CPU-only service on 2026-11-09. The existing preprod GPU service
was put into manual scaling **0** as an operational cost hold; voice input is temporarily
unavailable, while typed Studio input remains available. This branch prepares its replacement;
it does not deploy it or reactivate the old GPU image. Production is unchanged.

Previous real qualification established that the private routing/DNS isolation and Qwen RU/EN
inference worked. Whisper Small INT8 without hints preserved oval terminology but missed rare
prong/pear terms in 3 of 8 synthetic cases. Those results are not CPU acceptance. The CPU candidate
adds balanced orthographic hints and local VAD; accuracy must also be checked on independent
negative, non-jewelry and no-speech controls. Synthetic speech does not qualify real microphones,
accents, background noise or the final deployed Studio path.

## Runtime and trust boundary

One standalone service, separate from the API and text LLM, runs
`Systran/faster-whisper-small` with faster-whisper/CTranslate2 INT8 on **CPU only**.
It has no Parser, Knowledge, database, Asset or Product State dependency. Speech recognition
returns an untrusted editable transcript. It never submits a Message or changes canonical state.
The user reviews/edits and explicitly submits through the existing text path.

A fixed balanced RU spelling list (metals, shapes, stone names and prong terminology; see
`HOTWORDS` in `engine.py`) and EN hints (`pear cut`, `prong setting`) bias spelling only. There are no requirement templates, defaults or transcript
replacements. When no RU/EN language hint is supplied, no terminology hint is injected.
Silero VAD is bundled by the pinned faster-whisper package and runs locally. It reduces non-speech
hallucination risk but does not guarantee perfect transcription. No network fallback exists.

`LocalEngine` verifies every model artifact, starts one subprocess with two CPU threads and one
worker, and serializes inference. A 40-second inference timeout terminates the subprocess and
fails readiness. Model initialization is bounded by 210 seconds; Cloud Run startup by 240 seconds.
The libraries' stdout/stderr and exceptions are suppressed at the model boundary. Request PCM
and result references are released before waiting for the next request, without claiming secure
memory erasure. Runtime performs no model download or telemetry.

## Existing contract and privacy

`POST /internal/v1/transcriptions?language=ru|en` accepts raw WAV, WebM/Opus or Ogg/Opus.
The language hint is optional. Remote URLs, arbitrary destinations, other query parameters,
MP4/M4A, streaming and Hebrew remain unsupported.

The existing schema `1.0.0` returns status/text/language, duration and processing milliseconds,
and the actual model ID/revision. Empty decoded speech returns `silence` with empty text and
null language. Errors remain redacted: invalid 400/422; unsupported audio 415; size/duration 413;
upload timeout 408; busy 429; decode/inference timeout 504; model unavailable 503.
No public API schema or database migration is introduced.

Limits remain 10 MiB compressed input, 60 seconds decoded mono 16 kHz float32 audio, eight-second
decode timeout, six-second decoder CPU budget and Linux 768 MiB decoder address-space bound,
ten-second upload timeout, concurrency one, and 8192 output characters. Decoding uses bounded
pipes and explicit input/container protocols. No audio or transcript is logged or durably stored.

The browser calls only the existing tenant/session-authorized API proxy. It gets no STT service
credential. The API obtains an exact-audience Google ID token server-side. Multipart ingress may
spool transiently to ephemeral storage and closes/removes the upload afterward. Studio appends
the transcript to editable input without automatic submission. Manual typing survives STT errors.

## Private deployment and GPU retirement

`infra/terraform/preprod/stt.tf` retains the existing internal ingress, mandatory invoker IAM,
API-only invoker grant, separate runtime identity, private caller routing, inference deny-all
IPv4/IPv6 egress, authoritative empty private DNS root and A/AAAA sink. These are retained privacy
controls, not a requirement to dedicate a GPU. There is no NAT, gateway, public STT endpoint,
service-account key, database or Asset grant.

The CPU service is **2 vCPU / 2 GiB, request billing, min 0, max 1, concurrency 1**. No GPU selector,
GPU resource or CUDA/Torch dependency remains. No permanent warm instance is provisioned.
Service-level AUTOMATIC scaling explicitly clears the operational manual-zero hold only when
the reviewed CPU image is deployed. Never restore automatic scaling with the old Qwen GPU image.

Deployment remains the existing audited preprod saved-plan flow. Before coordinator deployment:

1. Independently review this branch and its CPU qualification evidence.
2. Build/verify the exact CPU image from `infra/docker/stt.Dockerfile`; retain digest, manifest and
   hash lock receipts. Point `STT_IMAGE` to that CPU digest and record CPU resource approval in
   `STT_RESOURCE_APPROVAL_REFERENCE`; do not reuse the old GPU digest.
3. Inspect the exact saved plan: same private service, 2 CPU/2 GiB, no GPU, automatic min 0/max 1,
   IAM/network preserved. Apply only through existing checksum/configuration/generation bindings.
4. Verify actual revision/resources, private IAM, DNS/egress isolation, real RU/EN microphone
   transcripts, editable input and explicit Submit. Passing mocked tests does not prove these.

Do not empty `STT_IMAGE` as a retirement shortcut: it would delete Terraform-managed protected
resources. The old GPU revision/image is historical until reviewed cleanup; it must receive no
traffic or allocations. Failure rollback is voice disabled/manual typing, not GPU reactivation.

## Reproducible model and dependencies

* Python 3.12.14 slim-bookworm linux/amd64 base digest:
  `sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a`.
* Model `Systran/faster-whisper-small`, revision
  `536b0662742c02347bc0e980a01041f333bce120`, MIT; `model.bin` 483546902 bytes,
  SHA-256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`.
* `faster-whisper==1.2.1`, `ctranslate2==4.8.5`, `huggingface-hub==0.36.2`, `numpy==2.2.6`;
  transitive hashes in `requirements-linux.lock`. These replace Qwen/Torch/CUDA solely inside STT.
  faster-whisper supplies the CPU decoder and bundled VAD; no new external inference service.
* `imageio-ffmpeg==0.6.0` remains the bounded local audio decoder.

Build acquires the exact snapshot and checks the known weight hash. The generated manifest binds
every top-level artifact; startup verifies the manifest, file set, paths and all hashes before
local-only model loading. The container digest binds the manifest. Missing/tampered artifacts fail
closed. No model weights are committed. Offline flags supplement actual network denial.

```sh
uv pip compile apps/stt/pyproject.toml --extra model --extra build \
  --python-version 3.12 --python-platform x86_64-unknown-linux-gnu \
  --generate-hashes --no-annotate --output-file apps/stt/requirements-linux.lock
docker build --platform linux/amd64 -f infra/docker/stt.Dockerfile -t jewelai-stt:review .
```

## Targeted verification

```sh
python3 -m pytest -c apps/stt/pyproject.toml apps/stt/tests -q
python3 -m ruff check apps/stt
python3 -m ruff format --check apps/stt
terraform fmt -check infra/terraform/preprod/stt.tf
python3 infra/terraform/check_invariants.py
git diff --check
```

Normal CI uses fake recognizers, real synthetic codec inputs and no model/network inference.
Real model qualification is separately identified in the PR; it must include original fixture
hashes, unseen controls, actual outputs, inference duration, offline execution and memory limits.
macOS decoding tests do not qualify Linux RLIMIT_AS. No broad API suite or Full Regression is
needed for this isolated model/resource change.

Previous measurement (unmodified Small, synthetic only): 2 CPU/2 GiB warm private HTTP
3.069–3.890 seconds, peak process RSS 1009.4 MiB; true cold HTTP 15.368 seconds. Changes to hints,
VAD and subprocess execution require candidate-specific evidence. Scale-to-zero does not remove
cold starts. Keep user-visible latency and accuracy limitations explicit.

## CPU candidate evidence (2026-11-09; not a deployed qualification)

Actual production engine/decoder/app in a Docker container with networking disabled, 2 CPU/2 GiB
and the unprivileged runtime user: 24/24 HTTP 200, **23/24 content controls PASS**. This includes
8 original byte-identical fixtures and 16 independent/negative/noise cases. Exact-token negation
checks preserve RU/EN prohibitions; no ASR output replacement is performed. The remaining synthetic
RU failure is `Оставь овальный камень…` → `Оставься вальный камень…`. Keep this FAIL visible.
Small with the earlier narrow hints scored 16/18; Medium scored17/18 and was slower (6.7–9.4s),
so increasing the model/hardware was not selected. The balanced Small candidate remains a review
candidate, **not full STT acceptance**. Model peak RSS711544KiB; local model-ready1.633s. These are
not Cloud Run cold HTTP or real-microphone measurements. See the PR evidence for all actual outputs.
The standalone mocked/codec/security regression suite passed57 tests; this is separate evidence.

## Reviewed CPU release transition

Historical STT_IMAGE/approval values now fail Terraform validation, rather than silently clearing
manual-zero. Only the code-reviewed CPU digest and exact digest-bound CPU-only approval may pass.
The [PR175 release handoff](../../docs/operations/stt-cpu-release-pr175.md) records the immutable
image, actual focused inference/codec/timeout evidence, retained RU failure and rollout sequence.
No activation is performed by this implementation. Existing23/24 evidence remains unchanged.
