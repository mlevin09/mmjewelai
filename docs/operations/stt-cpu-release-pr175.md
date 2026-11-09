# STT CPU release: PR #175 coordinator handoff

Status: prepared for independent review; not deployed. The Studio CPU journey remains unverified
until coordinator rollout and RU/EN microphone QA. Do not reactivate GPU.

## Immutable release

- Image: `europe-west1-docker.pkg.dev/mmjewellai-preprod/jewelai-preprod/jewelai-stt@sha256:baf8914f1e8c872bb94026877f026c3c73c281bd78a181f758d5d947b4340d22`.
- Runtime/recipe source: `5ec38362c75facb3288762386b7545a998d49d7d`; every executable STT
  module, dependency lock and Docker recipe matches that commit and the reviewed working tree.
  Subsequent changes only add the Terraform release gate, its tests and documentation.
- Build: `f86b0cbd-1cf9-4c0c-b278-0ced1e4f2907`, SUCCESS, 2026-11-09.
- Model: `Systran/faster-whisper-small`, revision `536b0662742c02347bc0e980a01041f333bce120`;
  `model.bin` SHA256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`.
- faster-whisper1.2.1, CTranslate2 4.8.5, numpy2.2.6; complete pinned hash lock in apps/stt.
- Two CPU threads, INT8, one worker; 2CPU/2GiB container, no accelerator, no Torch/CUDA package.

## Fail-closed transition

The Terraform variable validation uses a code-reviewed allowlist containing only the image above.
It also requires the exact paired CPU resource approval. This is an operational acknowledgement,
not a secret or a replacement for GitHub Environment/WIF/coordinator authorization.

After independent review, coordinator sets both existing preprod variables together:

```text
STT_IMAGE=europe-west1-docker.pkg.dev/mmjewellai-preprod/jewelai-preprod/jewelai-stt@sha256:baf8914f1e8c872bb94026877f026c3c73c281bd78a181f758d5d947b4340d22
STT_RESOURCE_APPROVAL_REFERENCE=cpu-only:2cpu:2g:min0:max1:sha256:baf8914f1e8c872bb94026877f026c3c73c281bd78a181f758d5d947b4340d22
```

Historical GPU digest, historical approval, missing approval, mixed CPU/GPU pairs and any other
image digest fail validation. A routine deployment retaining the old variables fails before apply;
it cannot clear manual-zero or mutate the historical STT template. Future CPU images need a
reviewed allowlist update. Existing workflow fingerprint binds both inputs at plan and apply.
No deployment workflow or required check is changed.

The held live service remains manual scaling0. Only the reviewed CPU transition may replace its
image/resources and set automatic min0/max1, concurrency1, request billing. Do not empty STT_IMAGE
as a deletion shortcut. Failure fallback is voice disabled/manual typing, never GPU rollback.

## Real CPU qualification, separately from CI

One release build ran actual LocalEngine + decoder + FastAPI HTTP under Docker --network=none,
--cpus=2, --memory=2g and the unprivileged runtime user. No fake recognizer or external ASR.
The original failing audio SHA was checked unchanged. Earlier 23/24 corpus remains unchanged
point-in-time evidence; it was not rerun.

| New/rechecked synthetic input | Actual transcript | Content result |
| --- | --- | --- |
| Оставь овальный камень без изменений. Не добавляй боковые камни. | Оставься вальный камень без изменений, не добавляй боковые камни | FAIL retained |
| Сохрани овальную форму камня. Не меняй серебряную шинку. | Сохрани овальную форму камня, не меняй серебряную шинку | PASS |
| Сегодня хорошая погода. Я иду в магазин за хлебом. | Сегодня хорошая погода, я иду в магазин за хлебом | PASS |
| Please send the meeting notes tomorrow morning. | Please send the meeting notes tomorrow morning. | PASS |
| Keep the round sapphire. Do not add a diamond. | Keep the round sapphire, do not add a diamond. | PASS |

All5 HTTP200; content4/5. Speech2.114–2.711s; local model-ready1.527s (not cold Cloud Run HTTP).
Peak child RSS700532KiB, parent52140KiB. No larger model/hardware or post-recognition word
substitution was introduced. The retained synthetic error is not declared fixed or attributed
conclusively to TTS. Practical dictation requires editable text and human QA, not perfect accuracy.

Actual release model also processed WebM/Opus and Ogg/Opus: both HTTP200. WAV is covered above.
A SIGSTOP of the actual inference process exercised the existing40s deadline: HTTP504 after42.134s
including bounded termination, health503. Explicit process restart restored HTTP200 inference.
This proves engine restart, not a deployed Cloud Run liveness replacement. Existing silence/noise,
private IAM and DNS/egress receipts are reused where unchanged; CPU live/private/browser checks
remain distinct from offline-container evidence. No audio/message persistence or automatic Submit.

## Coordinator review and rollout

1. Review the exact PR HEAD, immutable image, release gate and qualification limitations.
2. Review the saved-plan preview and its source/input/checksum bindings; do not apply a partial or
   failed plan. The authoritative deploy must use the existing audited workflow on the reviewed
   merged SHA, with saved plan checksum, configuration fingerprint and object-generation binding.
3. Inspect STT image replacement, removal of GPU selector/limit, 2CPU/2GiB, automatic min0/max1,
   request billing; preserve internal ingress, IAM identity/binding, VPC and DNS/egress controls.
4. Apply only through the coordinator-owned reviewed workflow, never local apply or replan.
5. Verify the actual CPU revision/private route, cold HTTP latency, IAM denials and recovery;
   reuse unchanged network-isolation evidence or repeat only changed controls.
6. In authenticated Studio verify real RU and EN microphone → editable transcript → explicit
   Submit. Distinguish prerecorded browser automation from human microphone acceptance. Check
   no auto-submit and typing preserved on denied microphone, timeout and unavailable STT.

No CPU service was activated by development. UI issues belong to the coordinator with exact
reproduction; no speculative Studio changes are included here. The separate text LLM is untouched.

## Costs and limits

Request-based planning rate for2CPU/2GiB: 2×$0.000024 +2×$0.0000025 = $0.000053 per billed second,
plus requests/startup, storage/DNS/network and before free tier/tax. At prior2.555s warm inference,
1000 recordings are approximately$0.14 compute, excluding cold starts. This is not an invoice or
an all-inclusive monthly price. Min0 means no permanent warm CPU commitment; cold HTTP latency
for this release has not been measured. Never substitute local model-ready time for that measure.
Source: [Cloud Run pricing](https://cloud.google.com/run/pricing).

## Saved full-platform preview (read-only, not an apply artifact)

Full refreshed plan against the existing preprod state completed with **0 add/3 update/0 destroy**.
Binary preview: `/tmp/stt-final/cpu-release.tfplan`, SHA256
`ae686058461d3279543c0bfb7f1aba6124d042eba9d0e03eb3d3e994f8fd05aa`.
It uses current live API/worker/web image digests, the reviewed CPU image and exact CPU approval.
It is NOT the post-merge workflow plan and must never be applied locally. Full binary/JSON can
contain sensitive state and are not committed or published with general evidence.

Changed addresses (all in project **mmjewellai-preprod**, despite historical resource labels):

- `google_cloud_run_v2_service.stt[0]`: manual0 → automatic min0/max1; historical GPU digest →
  pinned CPU digest;4CPU/16GiB/L4 →2CPU/2GiB/no accelerator; cpu_idle false→true. Internal ingress,
  service account and ALL_TRAFFIC inference VPC/subnet/tags unchanged.
- `google_identity_platform_config.preprod`: phone_number `[enabled=false,test_phone_numbers={}]`
  → absent block. No product code/config change was made for this provider/default difference.
- `google_monitoring_dashboard.production`: server-returned name/etag omitted; absent tile
  xPos/yPos defaults become explicit zero. This address manages the PREPROD project dashboard.

The coordinator must review these two non-STT normalization differences explicitly; do not silently
approve unrelated actions, use target-apply, alter ignore_changes or suppress drift. The ordinary
post-merge workflow also builds app images, so its authoritative saved plan must be inspected again
before applying the exact checksum/configuration/object-generation-bound artifact.

Initial preview failed on local ADC quota-project403. A single retry used documented temporary
`USER_PROJECT_OVERRIDE=true`, `GOOGLE_BILLING_PROJECT=mmjewellai-preprod` and
`GOOGLE_CLOUD_QUOTA_PROJECT=mmjewellai-preprod`; no local credential/IAM/provider source changed.
See [provider quota configuration](https://github.com/hashicorp/terraform-provider-google/blob/main/website/docs/guides/provider_reference.html.markdown).

## Focused execution ledger / DoD

- D1: PASS locally: native Terraform gate5 denied cases +1 allowed saved plan;3 existing STT
  infrastructure guards PASS; full refreshed platform CPU preview completed. Initial allowed-path
  probe failed while the release digest was still a placeholder; after actual build digest binding,
  the focused probe passed. No repeated unchanged command expecting a different product result.
- D2: actual pinned CPU engine4/5 new/rechecked content controls PASS; retained exact RU failure
  FAIL. Earlier57 tests and23/24 corpus at5ec38362 remain evidence for unchanged runtime; no claim
  of perfect accuracy. New genuine codec and timeout/restart evidence recorded above.
- D3: immutable image and exact variable pair prepared; full preview retained for review. Independent
  review/authoritative workflow plan approval remain coordinator gates, not developer acceptance.
- D4: NOT TESTED on CPU preprod: not deployed. Human RU/EN microphone QA and cold/private route
  verification follow the reviewed rollout. Previous GPU microphone proof is not CPU acceptance.
- D5: no GPU use/reactivation, paid ASR, warm CPU, Parser/Knowledge/LLM/production change, merge,
  apply or deployment. One Cloud Build execution (~172s),9 real inference attempts including the
  intentional stopped-process timeout and two codec requests. No Full Regression/broad API suite.
- D6: report retained failures, hashes, source/runtime binding and actual CI separately. New native
  test may SKIP where Terraform is unavailable; local native qualification is PASS, never infer
  native guard execution merely from a green hosted job.
