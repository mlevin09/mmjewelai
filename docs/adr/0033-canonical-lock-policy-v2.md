# ADR 0033 — Canonical LOCK Policy evaluation v2 (KNA2-003)

Status: Owner-approved Option A; implementation awaiting independent review.
Date: 2026-10-28.
Scope: existing issue [#117](https://github.com/mlevin09/mmjewelai/issues/117), nested LOCK consistency only.

## Context

The flat KnowledgeRuntimeState identifies a Knowledge release, not a current canonical revision.
It can be manually constructed, incomplete or stale. Some nested State wrappers are only present
inside aggregate values. Seven baseline probes showed APPLIED while revise_design rejected the
corresponding protected change. A richer caller-authored locked summary is not authoritative.

Knowledge Library is an independent reusable JewelAI component. Prompt Enrichment is a consumer,
not its owner. The fix belongs to shared Domain/Policy code.

## Decision and exact public interface

CANONICAL_POLICY_EVALUATION_VERSION = "2.0.0"

```python
KnowledgePolicyEngine.evaluate_canonical(
    revision: AnyDesignRevision | object,
    proposal: RuntimeStateProposal,
    *,
    expected_revision_id: UUID,
    effective_state: KnowledgeRuntimeState | None = None,
) -> PolicyEvaluation
```

The revision and expected revision identity are required. The selected engine runtime is validated
through existing version-aware projection. Any supplied effective state must match the exact
Knowledge package/version/runtime hash, existing group IDs and complete canonical target set.

LOCK authority comes exclusively from the supplied, fully validated canonical revision. The function
does **not** authenticate its origin, fetch a database revision, prove freshness, or authorize a
mutation. Trusted callers must load the authorized organization/session revision and retain their
existing revision/CAS, release-pin and transaction controls. A syntactically valid supplied revision
is not evidence of database currency.

Effective state is optional only for normal sequential proposal precedence; canonical authority is
never optional. It is not evidence that earlier proposals were committed or authorized. Forged or
stale effective lock flags cannot change the canonical protection result.

## Shared protection semantics

lock_protection.state_fields is the extracted original recursive revision traversal, including
stable group/component/element identity. Both ordinary revise_design and canonical Policy reuse
first_locked_change to compare complete intrinsic locked wrappers, including value, origin,
sources/provenance, uncertainty/rationale, confirmation and lock metadata.

Canonical policy also blocks a target at/below any intrinsically locked ancestor using exact tuple
segments (not string-prefix tests), including same-value proposals. An ancestor lock never changes
a child's intrinsic locked flag. Reference Binding LOCKED and PreservationIntent.LOCKED remain
separate meanings.

For a supported aggregate value replacement, validate the actual target State type and enclosing
Design schema, including existing stable-ID uniqueness. Missing aggregate members are rejected,
not merged. Full model_dump(mode="json") replacement snapshots make all members explicit. An
explicit schema-valid empty collection can remove unlocked items; any removed/rekeyed/changed
locked descendant still blocks. Invalid/incomplete replacements raise bounded ValueError before
APPLIED, without adding a public outcome/reason. Non-value proposals cannot erase locked descendants.

The validated replacement is retained as a detached, serializable snapshot in both the proposed
and APPLIED result values; the LOCK guard never checks one value and returns unchecked input.
Schema1.1 canonical evaluation rejects arbitrary iterables (including one-shot generators nested
inside dict/list/tuple/model fields) before target validation, without consuming them. Supported
replacement containers are explicit dict/list/tuple snapshots and existing typed models. Repeated
evaluation is deterministic and does not mutate caller collections. Historical Schema1.0 behavior
is unchanged. This repairs independent-review R1 in the same issue/PR, not a new contract version.

These replacement checks apply to Schema1.1 canonical evaluation. Historical Schema1.0 flat leaf
proposal/value behavior is retained, including validation deferred to the canonical transition;
canonical v2 still obtains direct LOCK authority from its required v1 revision.

A temporary State wrapper using the existing revision event source is used only for Pydantic type
validation. It is never persisted, returned as user authority, or substituted for canonical
provenance. No new user fact, source, confirmation or lock is created by evaluation.

Protected decisions retain outcome BLOCKED / reason locked. Existing release/source membership
checks and precedence remain; policy effect prose is never interpreted. No new targets/rules.

Explicit confirm_field, lock_field and unlock_field retain their existing behavior, including the
approved metadata-transition exception under ancestors. Unlock never cascades independent locks.

## Compatibility and bypass closure

The original evaluate(state, proposal) retains historical flat v1 leaf semantics and its result
contract. It rejects a Knowledge1.1 runtime, expanded v1.1 projection or expanded target with
ValueError requiring canonical v2. The frozen v1 target grammar and existing v1.1 target registry
are reused; composition/decorative/component paths cannot evade this by stripping ancestors or
using an old Knowledge1.0 runtime. Unknown ordinary v1 targets retain the old unknown-target result.

The actual production consumer enrich_prompt now always calls evaluate_canonical, passing its
unchanged original revision and a derived effective state for sequential precedence. API callers
continue through that consumer; no database/API/auth contract change is necessary.

Historical Knowledge source/runtime, State/Matrix/result DTOs, schemas, release pins and stored
hashes are unchanged. No historical cycle is rerendered/backfilled. Corrected new evaluations can
produce a BLOCKED result where the old algorithm incorrectly returned APPLIED; that is the intended
defect correction. Existing current/historical prompt hash regressions remain required.

## Alternatives

- Keep flat state or attach private/optional lock summaries: rejected; omitted/forged/stale context
  remains a bypass and lacks canonical revision identity.
- Version a full durable protection DTO: unnecessary for this fix; larger contract and persistence
  surface. Owner approved required canonical input instead.
- Prompt-Enrichment-only guard: rejected; would leave reusable Policy consumers inconsistent.
- Block every v1.1 operation: rejected; unrelated unlocked siblings must remain usable.

## Verification and limits

LCK-001..016 is covered by test_canonical_lock_policy.py, existing test_revisions.py /
test_knowledge_policy.py and real sequential consumer tests in test_canonical_lock_enrichment.py.
Baseline seven diagnostic RED scenarios were reconfirmed on cdfa997 before source changes.
New tests cover locked ancestors/hidden coating, complete aggregate replacement/deletion/rekey,
source/uncertainty/origin changes, exact segments, same-value behavior, explicit non-cascading
transitions, Unknown/N/A, v1 leaf/side-group behavior, forged/stale/incomplete contexts, wrong
release/revision, partial/malformed aggregates, duplicate stable IDs, determinism and immutability.
Positive compatibility controls are GREEN-before/GREEN-after, not falsely reported as baseline RED.

No Knowledge1.1 session integration, catalog change/activation, professional rule execution,
persistence migration, provider/worker/Web/image path, deployment or merge is part of this decision.
Independent review must inspect aggregate completeness, legacy rejection surface and the exact
caller currency/CAS boundary; unit tests do not prove live database freshness.

## LCK acceptance trace (overlapping assertions, not additive test counts)

| Case | Executable coverage | Baseline / correction evidence |
| --- | --- | --- |
| LCK-001 | test_parent_lock_blocks_child_even_same_value | Parent/child defect RED; new canonical path GREEN, including conservative same-value |
| LCK-002 | test_parent_lock_blocks_reset_and_nested_addition; coating unlock parity | Nested reset/add/remove/silent-unlock blocked; inputs retained |
| LCK-003 | test_complete_aggregate_lock_parity | Complete aggregate replacement cannot change/remove protected descendant |
| LCK-004 | test_unlocked_sibling_and_exact_segments | Unlocked sibling and shank_extra allowed with exact protected wrapper preservation |
| LCK-005 | aggregate parity component remove/rekey | Stable-ID protected child cannot disappear under parent replacement |
| LCK-006 | aggregate parity decorative remove/rekey | Stable-ID decorative descendant preserved |
| LCK-007 | existing Revision/Policy stable side-group tests; canonical v1 leaf/group test | Historical group targeting/deletion/rekey controls GREEN before/after |
| LCK-008 | test_special_transitions_do_not_cascade; existing transition regressions | Explicit transition exception unchanged, independent child lock remains |
| LCK-009 | provenance, source-only aggregate and full Derived metadata tests | USER_CONFIRMED/source/origin/uncertainty/rationale cannot bypass |
| LCK-010 | test_provenance_cannot_bypass_parent; foreign source test | Knowledge lineage validated even when lock blocks |
| LCK-011 | test_none_unknown_not_applicable_and_keep | Existing availability/KEEP semantics retained; no Unknown redesign |
| LCK-012 | v1 flat/canonical equality, existing domain and prompt goldens | Historical v1 semantics/hashes retained, new v2 does not rewrite history |
| LCK-013 | nine paired aggregate policy/revise_design assertions | Policy BLOCKED/locked and canonical RevisionConflict on same valid edits |
| LCK-014 | hidden coating parity; exact shank/shank_extra sibling test | Hidden State included via typed traversal; exact tuple ancestry |
| LCK-015 | forged/stale/incomplete/release/revision tests; determinism/immutability | Flat summaries never replace canonical lock authority; mismatch rejects |
| LCK-016 | partial/malformed aggregate and duplicate ID tests | Reject invalid/incomplete snapshot before APPLIED; explicit valid empty removal allowed |

The real consumer tests additionally cover allowed proposal then locked descendant, locked ancestor,
and allowed complete aggregate replacement then protected descendant. They forbid use of the old flat
method and compare deterministic results with reversed caller proposal order. All proposal processing
retains the existing deterministic sort; the original revision is unchanged.
