# ADR 0046 — Opt-in ST-01 first-creation binding and retained fallback reply

Status: implementation proposal under the coordinator's narrow ST-01 disposition;
not independently accepted, activated or deployed.

## Context

The existing Parser1.3 recognizes earrings in the pinned Library but cannot propose
that canonical field through the old Dictionary bridge. RU creation wording also
retains preference evidence. Changing the old Parser or pretending that it emitted
new facts breaks frozen source/history verification. The coordinator approved a
separate versioned ST-01 binding evidence/read contract, plus opt-in first reply
retention, within the first-story pilot. No provider was selected or authorized.

## Decision

Use `jewelai.st01.first-turn/1.0.0` only for the new opt-in first-turn route. Its
immutable receipt binds organization/session, exact original user Message/hash,
Parser1.3 evidence/hash, qualified Knowledge release binding, reviewed mapping IDs,
exact spans/values, parent/result revisions and initial enrichment cycle.

Only an unambiguous first RU/EN creation assertion can bind explicitly chosen
product type, product-body material and adjacent material color. This is neither
a global preference promotion nor an execution of policy prose. Questions,
comparisons, conditions, alternatives and informational requests are not selection.
Creation intent requires the product to be the direct object of the request:
source-backed attribute/adjectival modifiers may precede it, but information/advice
or an embedded topic do not grant selection authority. A desire verb alone is
insufficient. Recognized aesthetic wording qualifies syntax only, never an accepted
style value. Uncovered or informational complements remain unresolved without a
blacklist of information-request synonyms. The entire relevant post-nominal
construction must be covered by sourced nominal modifiers and permitted syntax;
a leading preposition is not proof for the rest of the clause. Native proven
assertion boundaries preserve independent requests; a bare negator cannot hide
an unchecked action. Count/component words qualify syntax only, with count,
placement and groups still unresolved. A known positive creation action may
close a postposed RU request; unknown informational actions are not admitted.
Product metal additionally requires a direct source construction, not a Parser
subject hint. Known/confirmed/locked incompatible values cannot be overwritten;
compatible facts retain original authority. Sapphire placement/count and all
unbound input remain source evidence, not inferred canonical parameters.

Revision, pin, existing F04 Matrix/plan, receipt and fallback text commit in the
existing locked/CAS initial transaction. Complete read/result construction occurs
before commit. A nullable `source_contract` marker selects a dedicated verifier;
old cycles keep the existing verifier, source bytes and hashes. New verification
recomputes binding and exact Matrix/plan from actual sources, not hashes alone.
Missing/tampered/mismatched evidence fails closed. The marker and receipt are
immutable in PostgreSQL. Downgrade refuses retained ST-01 history.

POST/GET `/v1/sessions/{session_id}/prompt-enrichment/first-turn` reuse tenant/session
authorization. POST consumes an existing original user Message and current revision;
no synthetic assistant Message or change to conversation-v1 is introduced. Duplicate
initialization does not regenerate a reply. GET retains original text and separately
reports current revision identity and whether the receipt's revision is still current.

The only implemented reply origin is explicitly `deterministic_fallback`. It states
accepted source-backed values and that remaining input is not accepted as parameters.
No model call, network access, implicit provider selection or simulated model success.
The existing internal untrusted conversational adapter remains unconnected.

## Alternatives rejected

- Reclassifying old Parser output, broad `Хочу` promotion, or rewriting historical hashes.
- Treating Library recognition, a Parser subject hint or a model draft as authority.
- Writing assistant text into user-only Messages or changing conversation-v1's enum.
- Committing first and discovering an invalid response/snapshot afterward.
- Regenerating a saved reply, introducing a recovery engine or adding future stories.

## Consequences and limits

This intentionally accepts fewer syntactic forms than a general language model.
Unsupported phrasing remains unresolved; it does not authorize guessed jewelry facts.
Legacy F04 planning is reused with its existing canonical-revision-only option for
ST-01, so unaccepted proposals cannot become the effective Product State. No new
clarification content, UI, provider, release activation or deployment is included.

A conversational model/runtime selection and independent naturalness/functional
acceptance remain separate open gates. Local SQLite and fake authentication prove
neither PostgreSQL migration safety nor live Identity Platform behavior; PostgreSQL
checks must execute behind the unchanged disposable-container safety gate.
