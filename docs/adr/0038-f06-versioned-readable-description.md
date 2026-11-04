# ADR 0038 — Additive F06 readable review outputs

- Status: implementation proposal for independent review; no activation
- Scope: Owner-approved F06-DEV-001 on `jewelai-v2`

## Context

F06 Phase A reproduced missing Schema 1.1 readable facts and nested State-wrapper
metadata leakage. Re-rendering Description3 would change frozen F05 bytes/hashes.
The Owner approved Description4 (4.0.0), IFP5 and Handoff5 (5.0.0), not a default
upgrade, public API expansion, new persistence or downstream provider cutover.

## Decision

An explicitly invoked `assemble_internal_final_prompt_v5` consumes the existing
source-verified `FinalPromptSnapshotV3`. It uses the same fact/constraint projection,
F05 protection evidence, compatibility discharge and native frontier/readiness.
Only presentation and family hash domains change. Pure semantic helpers are
shared with the frozen renderers; their historical output is tested for parity.

The internal typed renderer uses existing Dictionary terms and localized schema
property labels. Repeated components retain separate owner identities internally
and stable ordinal labels in review text; only explicit confirmed roles name them.
It never infers a role from an opaque ID. Known aggregate sections reference their
projected children instead of printing nested State metadata twice. Every fact
and active constraint receives internal coverage: rendered, represented by a
review section, or unsupported with a bounded reason. This coverage is neither
persisted nor a new public DTO field. Missing terminology remains a source term
marked for review, or a safe unsupported-property disclosure. There is no automatic
translation or new professional Knowledge.

Description4 and IFP5 retain 20,000 characters / 80,000 UTF-8 bytes and 32,000
characters / 128,000 bytes respectively. Overflow is an explicit existing typed
capacity failure. Construction is pure and cannot partially commit state.

## Compatibility and activation boundary

| Family | Reader/construction | Behaviour |
| --- | --- | --- |
| Description1 / IFP2.0, 2.1 / corresponding handoffs | existing readers/builders | frozen |
| Description2 / IFP3 / Handoff3 | existing F04 path | frozen |
| Description3 / IFP4 / Handoff4 | existing F05 path | remains current default |
| Description4 / IFP5 / Handoff5 | explicit Python builder and exact typed JSON readers | internal opt-in only |

Handoff construction dispatches exactly on version 5; old output is never
re-rendered. Existing preparation/rendering consumers explicitly reject versions
4 and 5 without downgrade. Historical decoders retain their version restrictions.
The public final-output endpoint still accepts only its existing versions, not 5.
No runtime output selector, public response union, state DTO or database is changed.
A public/UI selection contract, if desired, needs a separate Owner decision.

## Alternatives

Changing the old renderer in place would invalidate historical presentation
hashes. A new Product State/Matrix or independent readiness engine would duplicate
authority. Translating unknown professional terms would invent catalog content.
Expanding the public endpoint in this PR would exceed the approved internal gate.

## Consequences

The new internal output can be reviewed independently using current verified F05
snapshots. Default application output still has the historical limitations until
an independently approved activation. Full professional RU terminology is not
claimed for terms absent from the Dictionary; unsupported reasons stay visible.
No canonical, Parser, Knowledge, Matrix, rules, KEEP/LOCK or continuation policy
changes; no migration, provider calls, activation or deployment.
