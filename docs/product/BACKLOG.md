# JewelAI V2 task status

Last reviewed: 2026-09-29

This table replaces the original baseline-only backlog view with the current merged implementation state on `jewelai-v2`.

Status meanings:
- **Done** — merged implementation exists and relevant CI/tests passed.
- **Verified preprod** — merged implementation has also been exercised successfully in live preproduction.
- **Decision needed** — no implementation task should be inferred until product scope/priority is explicitly selected.
- **Not yet planned** — acknowledged future work with no current implementation issue/order.

| Order | Task / capability | Current status | Evidence | What remains |
| --- | --- | --- | --- | --- |
| 1 | Jewelry Design Schema v1 | **Done** | GitHub Issue #1 closed; implemented before PR #7 baseline | No foundation work pending |
| 2 | Role Profiles v1 | **Done** | Issue #2 closed; PR #8 | Product/domain tuning only when a concrete journey requires it |
| 3 | Domain Dictionary v1 | **Done** | Issue #3 closed; PR #9 | Extend reviewed terminology only when required |
| 4 | Question Catalog v1 | **Done** | Issue #4 closed; PR #10 | Expand catalog from validated product journeys |
| 5 | Rules Engine v1 | **Done** | Issue #5 closed; PR #11 | Add/adjust rules only from validated workflow requirements |
| 6 | Persistence + Runtime API foundation | **Done** | PR #12 | Continue schema/API evolution per product slices |
| 7 | Parser Proposal v1 | **Done** | PR #13 | Extend parsing behavior from validated inputs |
| 8 | Prompt Compiler v1 | **Done** | PR #14 | Extend provider/prompt policy only when required |
| 9 | Model Gateway + GenerationRun boundary | **Done** | PR #15 | Existing provider-neutral boundary retained |
| 10 | Asset ingestion/storage boundary | **Done** | PR #16 | No baseline gap |
| 11 | GCS storage + signed access | **Done** | PRs #17, #20 | No baseline gap |
| 12 | OpenAI image provider + Asset materialization | **Done** | PR #18 | Disabled in current preprod configuration; optional provider |
| 13 | Authentication + organization membership | **Done** | PR #19 | Production identity path remains a separate decision |
| 14 | Durable generation queue / worker / recovery | **Done** | PRs #21-#23 | No baseline gap |
| 15 | Authenticated reference upload | **Done** | PR #24 | Product UX validation remains |
| 16 | Web application core workflow | **Done** | PR #25 | Broader product journey UX still requires validation |
| 17 | Production GCP infrastructure definitions | **Done (code only)** | PR #26 | Live production provisioning is not established by this status |
| 18 | Google Generative Language image provider | **Verified preprod** | PR #32; JPEG compatibility PR #49; live generation smoke succeeded | Quality/cost benchmarking across scenarios remains product validation work |
| 19 | Isolated European preproduction platform | **Verified preprod** | PRs #33-#48; Deploy preprod run 36437152477 | Operational baseline complete |
| 20 | Google Cloud Identity Platform for preprod | **Verified preprod** | PR #39; live sign-in, token, membership-boundary and logout smoke recorded | Production identity decision remains separate |
| 21 | Public DNS + TLS + health readiness | **Verified preprod** | `preprod.jewellai.online` and `api.preprod.jewellai.online`; certificate ACTIVE; Web/API health 200 | No preprod infrastructure blocker |
| 22 | End-to-end Google generation + Asset finalization | **Verified preprod** | `gemini-3.1-flash-lite-image`; GenerationRun succeeded; Asset ready as validated JPEG | Expand validation to representative product scenarios |
| 23 | First real product/user journey validation in preprod | **Decision needed — NEXT GATE** | Preprod platform is now operational; current governance explicitly leaves product priority open | Select one user, workflow and success criteria; then create the next vertical-slice issue(s) |
| 24 | Production rollout | **Not yet planned** | Production Terraform exists, but live production state/identity/provider choices are not established | Do only after the intended customer journey and release criteria are explicit |
| 25 | A/B delivery / experimentation | **Not yet planned** | Mentioned in original baseline as later work; no current implementation evidence | Reassess after first validated product journey |

## Current conclusion

The original V2 foundation and the infrastructure needed to exercise it are no longer the bottleneck.

**The next gate is product validation, not additional platform construction.**

Before opening the next engineering feature issue, explicitly choose:
1. the first user/organization to optimize for;
2. the exact end-to-end workflow to validate in preprod;
3. the observable success criteria;
4. which missing capability is actually required by that workflow.

This does **not** designate any existing JewelAI product as the default priority. Product priority remains open until explicitly decided and recorded.

## Known capability gaps not yet represented as ordered V2 backlog issues

Current project direction has discussed additional input modalities such as image-to-text interpretation and voice-to-text transcription. These are not represented here as completed repository capabilities and should receive explicit specs/issues only if the selected product journey requires them.

Exact source templates and terminology still require domain review before production seed publication.
