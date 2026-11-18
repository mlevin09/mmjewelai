# ST-01 — source/contract delta and implementation evidence

## EN MASTER

Base: `ba422f81430a35d1dbaf6f781ee07e81b494a6f7` (`jewelai-v2`). Branch:
`codex/st01-first-natural-turn`, isolated worktree. This appendix is not a backlog.
Implementation, developer verification, independent acceptance, merge and deployment
are distinct. ST-01 is **not complete** while the conversational runtime gate is open.

Authoritative sources read: [Protocol v2.0](https://docs.google.com/document/d/1gVVHWON3wE1WGTsw9LXoDdO2xAMFF58aats9ROtSiAc/edit),
[Handoff](https://docs.google.com/document/d/19WHIOdmp-SepPD0Sp0bvOb_Ci_fs9AumIgbkkzm4n5M/edit),
[single Backlog](https://docs.google.com/document/d/168r6pekANdZZjymQpGTIkP_3qv53VqAMSGSw9uxDbfg/edit),
[architecture v0.4](https://docs.google.com/document/d/1ACoRQmcR23R9f512H77UKS_IhEfTA343gig5ej7XeeY/edit),
[original US-01 draft](https://docs.google.com/document/d/172ZGSU9G8N2WP6Aq7obbjQ4cnlMs7ST02VQM1lvPsog/edit).
Latest coordinator disposition excludes mandatory clarification and standalone
retry/recovery, approves the narrow reply contract and versioned ST-01 binding/read
contract, and preserves the old Parser/history. UI remains coordinator-owned.

## Actual baseline and precise incompatibility

RU: `Хочу элегантные серьги из белого золота с двумя сапфирами`.
EN: `I want elegant white gold earrings with two sapphires`.
Real persisted local SQLite HTTP, existing fake authentication, actual pinned Library:
raw Message exact; initial 201; RU product/metal unset; EN gold/white explicit,
unconfirmed; earrings evidence-only; sapphire/count unresolved; no retained natural
reply. Legacy Google-understanding calls: zero. Parser subject hints are not accepted
sapphire attachment or quantity distribution.

Read-only read-view probes for hypothetical earrings/gold/white transitions returned
`Stored revision is not the actual accepted ParserProposal transition` in both
languages, from `_verify_recorded_source_evaluation()`. No DB record was modified.
The coordinator subsequently approved the separate typed binding/read contract;
old cycles, old Parser evidence and historical hashes remain on their original path.

## Implemented opt-in boundary

See [ADR0046](../adr/0046-st01-first-creation-evidence.md).

- POST `/v1/sessions/{session_id}/prompt-enrichment/first-turn`, body
  `schema_version="1.0.0"`, `message_id`, `expected_revision_id`.
- GET at the same path returns the exact immutable receipt, current revision ID and
  `is_current_revision`; historical receipt is never presented as current State.
- The Message must already exist, be user-origin and belong to the authorized session.
- `jewelai.st01.first-turn/1.0.0` records exact source spans, accepted values, reviewed
  mapping IDs, Parser1.3 hash, full qualified Knowledge binding and parent/result/cycle.
- Only direct, unambiguous first RU/EN creation selections of product type, product
  material/color; no global preference promotion. Metal must be owned by the product
  in source text. Questions/conditions/comparisons/informational requests do not select.
- Existing accepted values and locks cannot be overwritten. No stone/group/count or
  other unspecified property is invented. Canonical values remain unconfirmed unless
  already confirmed through the existing authority path.
- The existing initial transaction atomically stages revision/pin/cycle/plan/receipt;
  full source/Matrix/plan/read validation precedes commit. Snapshot failure rolls back.
- PostgreSQL has immutable receipt/source-marker triggers and a guarded downgrade.
- Old initial and conversation-v1 contracts are unchanged. No model/provider is called.
- Reply is honestly labelled `deterministic_fallback`, accepted facts are displayed from
  actual bound evidence; remaining request remains unaccepted. No retry/recovery engine.

The internal `conversation_model.py` Protocol/context builder keeps immutable State
separate from immutable source evidence and rejects mismatched release identities.
Its `UntrustedConversationDraft` is not accepted State or a delivery permission.
It remains unconnected pending an approved conversational runtime.

## Exact Library identity reused, never activated by this task

Package `jewelai.preprod.recovered_core/1.0.0`, Knowledge contract1.1.0.
Runtime `dca0d4ae27155552745072a818f37a741be5983711ffbab834e198357133de57`.
Report `c3260a3e86dba45f796fb6db1004fc07384fe9e20310623cbba519fff52da12c`.
Archive `6f6d9b114efbdb923795f4f10776dc2a89b00e293d551a6e0c07a020e3395e6a`.
Actual archive/store and unchanged integration verifier were checked locally.
Existing mappings include LANG-EN/RU-EARRINGS, GOLD, WHITE, SAPPHIRE; count words
have no accepted mapping. Compiler/matcher/release loader are reused; no new catalog,
professional qualification or active promotion. TEST-ONLY fixtures remain test-only.

## Developer checks and limitations

Receipt ledgers are preserved outside the worktree; final exact-head results belong
in the PR. No local full API suite, Full Regression, manual CI rerun or live provider.
Combined targeted checkpoint: 39 PASS / 3 PG SKIP, 224.64s. Ownership module:
22 PASS, 24.41s. Native selection preview: API84 + Auth19 + Domain307 + CI174 =584
cases collected; blocked=[]; collection is not PASS. No Full run. Later scoped
assertion/source-version hardening has its own focused receipt; exact-head CI
remains the authoritative hosted gate. Follow-up final hardening: 3 PASS /12.58s
(RU/EN replay under another ambient source-version context; scoped rollback counts
suitable for the existing PostgreSQL fixture). Timings/failures are retained honestly.

Existing PostgreSQL container/cluster/job/freshness verification is unchanged; local
PG skips are NOT PASS. New gated PG tests cover real migration, immutable triggers,
retention/downgrade and atomic rejection.

Known resolved development failures: initial `None` field handling; strict timestamp
wire serialization; a test's incorrect empty-side-group expectation; canonical-only
planning needed for unaccepted proposals; material ownership control detected and
fixed `earrings with gold center stones` incorrectly becoming product metal. The
original Parser was not changed. No failing command was repeated without diagnosis.

CI metadata is expanded only to own the new declarations and exact shared-source
pairs. The historical ROLES fixture uses its immutable accepted ownership receipt;
a separate current-pair check retains fail-closed drift detection. Selector algorithms,
required checks, workflow dispatch and Full qualification policy are unchanged.

Earlier auto-review rejected commit because it recognized only Issue182 scope.
The coordinator supplied Owner pilot authorization provenance and the precise new
contract disposition. No alternate publication channel or bypass was used; actual
publication outcomes will be reported separately. No claim of independent acceptance.

### Open gates

1. Conversational model/provider/runtime is not selected or authorized. Existing
   Google config is legacy extraction, not approval for conversational inference;
   ADR0043's Qwen is a lab candidate, not an authorized conversational runtime.
2. Real-model naturalness, active Studio integration and live authentication are
   NOT TESTED. Fallback and fake-model checks are not these acceptance results.
3. New migration is not applied to shared/preprod/production. No catalog activation.
4. Final-head CI and real PostgreSQL outcomes must be reported from their actual run,
   not inferred from local SQLite. Development cannot self-accept the story.


## P1 review correction — informational intent is not selection

Independent review of `57a54d725918ae3f60a7f1cf818eea01a0d0da71` found one
shared authority defect: “I would like to know about white gold earrings”,
“Хочу информацию о серьгах из белого золота” and “I want advice about white gold
earrings” were treated as selections. These three persisted HTTP/reload cases
were reproduced RED: 3 FAIL /12.99s, each committed three explicit facts and a
new revision, with an incorrect accepted-values reply.

The fix requires a source-backed direct product object, not merely a desire verb
followed somewhere by Library words. The intervening phrase must contain only
permitted grammatical glue and source-backed adjectival candidates already
recognized by the current Parser; informational heads/complements remain uncovered.
A post-nominal informational complement is not admitted as creation either. The
old information-word blacklist is removed, not expanded. Unrecognized syntax
fails closed; this bounded deterministic grammar is not a general language model.
Aesthetic modifiers establish syntax only and are still not accepted style facts.

Targeted receipts: the new module 17 PASS /21.07s, existing first-turn regression
module 26 PASS /57.37s. Strengthened recognition controls 12 PASS /5.01s ensure
that vocabulary recognition was actually reached (rather than obtaining false
confidence from an unknown jewelry word). These 12 overlap the 17-case module;
do not count them as additional unique coverage. No broad API or Full run.

For all three exact reported inputs: POST201, selection_eligible=false, facts=[],
revision delta0, no accepted-values claim, GET200 and identical revision/receipt
from a new application instance. RED/GREEN Parser payloads are identical: the
correction is in authority intent, not in the frozen Parser or Dictionary/Library.
A read-only comparison against the independent review's two original positive
RU/EN records confirms identical Parser payloads and CreationFacts. Original
review artifacts were not modified. No existing record was rewritten or repaired.

The existing replay/tamper, scope/stale-CAS, protected authority, native correction,
historical receipt and atomic failure tests pass in the directly affected 26-case
module. PostgreSQL/CI evidence at the old SHA remains identified as old evidence;
new exact-head automatic CI must be reported separately. No schema, migration,
provider, UI, legacy Parser or historical verifier change is part of this correction.
CI ownership adds the complete intent-regression module for every future binding edit;
selector/workflow/required-check behavior is unchanged.

This resolves the reported class in the bounded executable scenarios as developer
evidence. Independent re-acceptance remains required; real model/Studio gates stay open.

## RU — основные результаты и ограничения

База и ветка указаны выше. Read-only пробы подтвердили несовместимость нового
перехода с прежним ParserProposal verifier. После согласования реализован отдельный
`jewelai.st01.first-turn/1.0.0`: Message/spans, Knowledge pin, Parser hash и точный
parent/result/cycle. Старые Parser/readers/hashes не переписаны.

Новые opt-in POST/GET first-turn сохраняют один immutable receipt. RU/EN однозначный
первый запрос может принять явно выбранные type/material/color. Вопросы, сравнения,
условия и информационные запросы не являются выбором; «хочу всегда explicit» не
введено. Металл должен относиться к изделию в исходном тексте, а не только в hint.
Sapphire/count остаются unresolved, групп и размеров система не придумывает.

Ревизия, pin, существующий Matrix/plan и reply сохраняются атомарно после полной
проверки результата. GET возвращает исходный reply и отдельно сообщает, является ли
его ревизия текущей после дальнейших corrections. Tenant/CAS и прежние authority
механизмы сохраняются. PostgreSQL trigger/downgrade проверки требуют реального
допустимого disposable PG; локальный SKIP не считается PASS.

Сейчас reply честно помечен `deterministic_fallback`: это не проверенный естественный
ответ языковой модели. Новый provider не подключался и не вызывался. Выбор runtime,
реальная naturalness, Studio и live authentication остаются открыты. ST-01 не
объявляется завершённой или принятой; merge/deploy/Knowledge activation отсутствуют.

Ownership metadata содержит новые точные пары хешей и тестов; историческое ROLES
доказательство закреплено за своей исходной конфигурацией. Selector/workflows/gates
не ослаблены. Ранее отказ auto-review на commit не обходился; фактический результат
публикации и exact-head CI должен быть указан отдельно.

### RU — исправление P1 независимого review

Три informational/advice запроса воспроизведены через HTTP и reload: RED3 FAIL,
12,99 с. Исправлено основание authority: изделие должно быть прямым объектом
creation/selection, а не темой информационного запроса. Покрытие исходными
модификаторами не принимает их как style-факты. Список запрещённых синонимов не
расширяется; неизвестная синтаксическая конструкция остаётся unresolved.

GREEN: новый модуль17 PASS /21,07 с; существующие first-turn регрессии26 PASS /57,37 с;
12 усиленных recognition-контролей PASS /5,01 с (это повторное подмножество17).
У трёх примеров теперь facts=[], selection_eligible=false, ревизия не меняется,
reply не объявляет характеристики принятыми; после нового экземпляра приложения
GET возвращает те же данные. RED/GREEN Parser evidence совпадает полностью.
Старые позитивные RU/EN evidence/bindings также совпали при read-only сравнении.
Новых контрактов/миграций/provider нет. Требуется независимая перепроверка;
разговорный runtime и Studio остаются непроверенными. Merge/deploy не выполнялись.
