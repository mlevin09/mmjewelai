# US-01 backend — Owner Input → Output, 19 November 2026

EN MASTER. Same Draft [PR #185](https://github.com/mlevin09/mmjewelai/pull/185),
branch `codex/st01-first-natural-turn`. Published parent `cc92685bfdeb58f718e02f1f5112f8339202136c`;
integration baseline `ba422f81430a35d1dbaf6f781ee07e81b494a6f7`.
Implementation evidence is not independent functional acceptance.

## Input and implemented output

Owner-approved D3: Qwen interprets original human text; Parser 1.3 independently
reads the same bytes; SO checks both against source, ownership, Dictionary/qualified
Library, Matrix/Policy and current State. Neither interpreter writes State.
D2-A: atomically save verified Message/State/input receipt, then read the committed
revision, request and validate natural wording, and retain a write-once reply.
The Owner separately approved additive receipt2/migration0023 in code only.
Latest instruction suspends all further Qwen runs/configuration and prioritizes
functional integration. It does not turn failed real-model scenarios into PASS.

**KEEP:** canonical revisions, source spans/Message IDs, historical Parser readers,
CAS, tenant checks, qualified release pins, Matrix, raw bytes, previous schema1.
**REWORK:** new schema2 arbitration and commit-before-response, optional explicit
runtime composition and context-aware critical reply checking.
**REMOVE from current uncommitted scope:** prior Google-first adapter and UI work;
preserved outside Git before restoration. ChatGPT owns the Studio integration.
No published historical commit was reset or rewritten.

Only product type, product-body metal material and adjacent metal color have the
existing approved writable first-creation bindings. Sapphires and counts remain
source-backed unresolved evidence; allocation, group, origin, weight and shape
are not invented. The result is an initial turn, not multi-turn clarification,
Final Brief confirmation or generation handoff.

## Backend/UI handoff

Existing route `POST /v1/sessions/{session_id}/prompt-enrichment/first-turn` accepts
`schema_version: "2.0.0"`, `turn_id`, `expected_revision_id`, exact `original_text`,
optional one qualified product `selections` item and optional user-reported transcript.
No preliminary Message POST is needed for schema2. Options are read through the
same scoped `.../first-turn/options` endpoint. GET with `turn_version=2.0.0` returns
committed evidence, exact reply, current revision/brief and historical/current flag.

201=new/delivered; 200=identical replay; 202=committed input with pending delivery.
Render delivered origin honestly (`model` versus labelled `fallback`). Same-turn
identical POST may finish pending delivery only; it must not repeat interpretation
or append State. GET/restart never calls the model. Changed identity/input or stale
revision conflicts, and unauthorized access remains concealed. Do not display an
unverified local draft as read-back source. Schema1 remains unchanged.

## Actual functional evidence

- Injected RU/EN HTTP text/dropdown/mixed/transcript flows use real API, SO, Matrix,
  SQLAlchemy and disk SQLite. Three supported facts commit; source-only sapphires/
  count do not acquire guessed placement. A new app reads identical retained reply
  and committed evidence with no model call. These are mocked-model tests.
- Missing Parser candidate is not automatic veto when exact independent qualified
  source proof suffices. Questions, rejected text, proposals/recommendations,
  unproven component ownership and competing values do not gain consent.
- Source/precommit rejection leaves Message/revision/receipt unchanged. After a
  legitimate commit, failed reply preserves State and delivers an honest fallback.
  Lost delivery can be finished by identical POST without another interpretation,
  Message or revision. Write-once delivery returns the retained winner.
- Rehashed raw source/decisions/reply tampering is rejected. Tenant, stale CAS,
  existing locked value and previous schema1 receipt checks remain covered.
- Newly found RED: same-valued `gold` at product and stone sources borrowed the
  first ownership decision; a model reply could call mentioned unresolved sapphires
  saved. Two failures reproduced. GREEN: ownership is per source occurrence;
  false saved claims fail closed, while a truthful `not saved` reference remains
  valid natural wording. No Parser algorithm or historical evidence was changed.

## Local execution ledger (overlapping checkpoints; do not sum as unique coverage)

| Receipt / purpose | Actual result | Seconds |
| --- | --- | ---: |
| qwen-transport, initial offline adapter | 20 PASS | 5.93 |
| input modes checkpoint | 4 PASS / 1 FAIL | 21.95 |
| corrected mixed/transcript controls | 4 PASS | 17.56 |
| guards checkpoint | 17 PASS / 1 FAIL | 72.04 |
| semantic source final checkpoint | 14 PASS | 7.91 |
| combined relevant modules, once | 144 PASS / 9 deselected | 280.19 |
| compact quote/transport | 5 PASS | 2.15 |
| compact wire through actual HTTP/State, MockTransport | 2 PASS | 23.79 |
| pending delivery recovery | 2 PASS | 9.42 |
| latest ownership/reply RED | 2 FAIL / 2 PASS | 14.09 |
| latest affected GREEN | 18 PASS / 36 deselected | 70.00 |
| CI exact-source ownership checkpoint | 1 PASS | 0.18 |

Early iteration failures are retained, not relabelled: unsafe fake bracketed prose;
missing owned counterpart handling; wrong test expectation about independent type;
source helper/import defects; mixed literal ownership; invalid dropdown validation
after rather than before model call. Each received a related correction before a
rerun. A scratch evidence lookup had a moved pytest-current path; it was a failed
read, not product acceptance. Full local API and Full Regression were not run.

Reproduce only the affected final cases:
```sh
python3 -m pytest -c apps/api/pyproject.toml \
  apps/api/tests/test_semantic_proposal.py apps/api/tests/test_natural_turn.py \
  -k 'same_metal_at_different_sources or compact_quotes or missing_or_repeated_quote or explicit_product or missing_parser_candidate or model_injected_claims or genuine_new_model_wording or rejected_precommit_read or compact_qwen_wire' -q
```
Previous combined144 checkpoint precedes compact transport/pending-recovery/final
source fixes; later focused evidence covers those changes. Exact-head hosted CI is
reported in the PR, never inferred from older green runs. Three PostgreSQL cases
are collected behind the unchanged disposable-target gate; local execution is
**NOT TESTED**, not PASS. SQLite does not qualify triggers/migration/downgrade.

## Existing real-model observations — not final-code acceptance

Inspected actual existing VM, model/runtime and `/health`; no new installation,
IAM or firewall change. Qwen3-1.7B-Q4_K_M.gguf SHA256
`d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5`;
llama.cpp b12110/cd959bae99ff4bed22bef2604f45241c09bbb8c8, context2048.
Existing runtime used six bounded synthetic calls across two CPU boots (~19 minutes
cumulative); initial/final VM state TERMINATED. Temporary credential files and own
probe payloads were removed; historical research results were retained.

Tiny JSON generation200/~9s; full RU semantics timed out; RU reply200/~100s but
without the required accepted canonical result. EN semantics200/~117s failed typed
semantic validation; EN reply200/~90s did not establish the complete natural turn.
No model failure wrote guessed State. These are **FAIL/incomplete** conversational
scenarios, not latency acceptance. They used an earlier adapter checkpoint; the
later compact wire/reference settings are **NOT LIVE VERIFIED**.

The [previous R1 report](https://drive.google.com/file/d/15qReuuUB9XBZNW6HPBseRq_k5DveBF_e/view)
identified a neutral B512 operational comparator, not a qualified professional
winner or product deployment. Initial adapter defaults did not fully match it;
this discrepancy was disclosed. Explicit reference settings were added locally
before the Owner stopped Qwen work; no deployed configuration changed. No unused
additional calls will be made. A 240-second diagnostic ceiling is not a Studio
response-time promise or an acceptable measured user experience.

## Open gates

| Gate | Status |
| --- | --- |
| Source→dual interpretation→SO→Matrix→commit→reply, injected model | Developer-verified focused PASS |
| PostgreSQL qualification | Local NOT TESTED; exact-head hosted gate required |
| Real final-code RU/EN interpretation/reply and latency | NOT VERIFIED; Qwen work deferred by Owner |
| Studio schema2 integration/live identity/reload | Coordinator-owned, NOT VERIFIED here |
| Shared migration/runtime activation/deployment | NOT PERFORMED |
| Independent acceptance | Pending coordinator review |

No cloud/production configuration, UI, Parser algorithm, professional Knowledge,
worker/provider image path or CI enforcement was changed. Only precise CI ownership
entries cover new code/dependency; workflows and selector algorithms are unchanged.
No merge, deployment, Full Regression or Knowledge activation.
