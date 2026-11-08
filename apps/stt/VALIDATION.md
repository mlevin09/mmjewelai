# STT developer evidence — 2026-11-08

Baseline: `jewelai-v2` `1fc5f73d258410f9c01e1aade8175c495312f048`.
Branch: `codex/self-hosted-stt`. Developer verification only; not independent acceptance.

## Functional Definition of Done

| Criterion | Actual result | Status |
| --- | --- | --- |
| Private internal byte-to-transcript service implemented | Versioned HTTP boundary, real bounded codecs, fake RU/EN recognizer contract tests | VERIFIED PASS for HTTP/codecs; real ASR NOT TESTED |
| Reproducible local model execution recipe | Exact revision, known weight hashes, full runtime/build locks, immutable base, startup integrity/offline loader | VERIFIED PASS for validation/loader contract; container build/GPU execution NOT TESTED |
| Invalid, unsupported, oversized, overlong, nonfinite audio and silence | Typed errors or empty silence response; recognizer not called for invalid/silent audio | VERIFIED PASS |
| Deadline/failure handling and cleanup | Model terminated on timeout; failed/dead model not ready; pipe decoding leaves no audio files | VERIFIED PASS for local tests; Linux address-space bound NOT TESTED on macOS |
| IAM and no Internet/public invocation | Disabled Terraform specifies internal ingress, API-only IAM, no NAT/LB, deny v4/v6 and DNS sink | VERIFIED PASS for config/validation; actual platform authorization/isolation NOT TESTED |
| Current text/Parser behavior preserved | No Parser/API handler/domain/persistence changes; focused dictionary/LOCK controls pass | VERIFIED PASS for scoped evidence; full product regression NOT TESTED |
| No unapproved spend or environment change | No resources, variables, secrets, deployments or runtime activation changed | VERIFIED PASS |
| PR review and independent functional acceptance | Submitted Draft only; coordinator owns independent acceptance | NOT TESTED / pending review |

## Local test execution ledger

Command prefix for STT tests: `PYTHONPATH="$PWD/apps/stt/src:/tmp/jewelai-stt-testenv" python3 -m
pytest -c apps/stt/pyproject.toml apps/stt/tests -q --tb=short`. Temporary environment contains
the pinned lightweight app/test dependencies, not the optional model stack.

| Run | Result | Duration | Reason/change |
| --- | --- | ---: | --- |
| STT 1 | 30 PASS, 9 FAIL | 14.25 s | macOS RLIMIT_AS unsupported; isolated decoder exited before decoding |
| STT 2 | 39 PASS | 3.69 s | Linux-only address-space gate; macOS keeps codec/CPU/deadline checks |
| STT 3 | 39 PASS | 3.78 s | Upload-buffer cleanup and bounded/redacted client response changes |
| STT 4 | 44 PASS, 3 FAIL | 4.02 s | New nonfinite tests had a missing Audio test import; diagnosed NameError |
| STT 5 | 48 PASS, 0 FAIL, 0 SKIP | 3.99 s | Import fixed; added empty-recognizer-result silence normalization |
| STT final | 48 PASS, 0 FAIL, 0 SKIP | 4.37 s | Explicitly drop the last model-process PCM/result before waiting for another request; assert this in the worker test |
| Parser focused controls | 2 PASS, 19 deselected | 0.96 s | Existing EN/RU dictionary distinctions and protected LOCK no-op behavior |

Parser command: `python3 -m pytest -c packages/parser/pyproject.toml
packages/parser/tests/test_parser.py -k 'en_ru_dictionary_resolution_and_semantic_distinctions or
locked_values_are_preserved_and_equal_values_are_noops' -q --tb=short`.

One Starlette/AnyIO test-client deprecation warning; no skipped tests counted as PASS. Synthetic
waveforms test the actual decoder; fixture transcripts test orchestration only. No real speech
recognition, customer audio, external inference API or paid generation call was executed.

Other checks: Ruff check/format and diff-check; Terraform fmt; preprod Terraform validate in a
temporary backend-free copy using the existing locked provider (Google 7.46.1); existing
`infra/terraform/check_invariants.py`; deployment workflow YAML parse. Initial provider-schema
attempts hit existing backend/sandbox restrictions; validation was moved to the backend-free
temporary copy rather than reading/mutating live Terraform state.

No API full suite, Full Regression, manual GitHub workflow, deployment, migration, cloud build,
model-weight download or production operation. Hosted CI status is reported on the exact PR HEAD,
separately from these local receipts. Docker is unavailable on this developer host; image digest
and full model manifest are NOT AVAILABLE, not fabricated.

## Owner Input → Output

Input: implement STT backend and reviewable economical infrastructure; no paid resource creation
before configuration/cost approval, no public/durable API invention, no Parser or UI changes.

Output: standalone backend + server-only client, bounded internal contract, offline packaging
recipe, disabled preprod configuration and exact-plan fingerprint extension. No Load Balancer.
Next resource gate: approve one L4/4 CPU/16 GiB, min 0/max 1, approximate $1.04652 per allocated
instance-hour plus DNS/registry/build usage; then qualify real GPU and network isolation.
Next public-contract gate: session-authorized transient audio ingestion and user review of transcript
before the existing Message flow. Precise proposal and limitations are in README.md.
