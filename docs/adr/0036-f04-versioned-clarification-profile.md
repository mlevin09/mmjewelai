# ADR 0036: F04 versioned clarification profile

Status: Owner-approved contract; implementation in progress. Date: 2026-11-01.

## Context

F04-A identified missing material-choice clarification, duplicate explicit-value deferral,
lossy availability projection and stale historical blockers. The Owner approved A–E and
technical T1–T6 in F04-B0-R1. Existing sessions and historical artifact hashes must retain
their original meaning. This decision does not authorize deployment or feature activation.

## Decision

Use the explicit opt-in `jewelai.prompt-enrichment.f04/2.0.0` profile, with separate Questions2
and Rules2. Preserve the five required targets and existing nine rules. The bounded
`ask_unresolved_product_body_material` rule has priority 950 and tie order 15; missing material
alone is not a new required field. Keep default session creation on the legacy profile.

Scope conflicts by actual owner, target and source Message. Strict equivalent explicit
requirements may yield one ordinary ParserProposal, retaining all source evidence. Material
choice uses existing active Dictionary IDs and cannot enable material preference acceptance.
Russian `хочу` retains existing preference semantics.

Represent availability as read-only evidence from the exact canonical revision. Current
unresolved causes must be separate from immutable answer history; only the approved causal
proof can discharge a blocker. Typed model validation or a Matrix decision alone does not
establish accepted canonical state, database currency or authorization.

The complete signed specification is the [F04-B0-R1 technical appendix](https://drive.google.com/file/d/1KeOThQYeuXHmM43Isn16ET2liBq32ou9/view)
(SHA-256 `c08b5542c6e7dbb647f828d303520710274810155bf0a2282fe4432a621d0e9f`)
and [Owner decision sheet](https://drive.google.com/file/d/11R_LKRmg-JgtvqO0ItmsRvgqn72xBtYX/view)
(SHA-256 `b7d62176620bec1e5cfe77a628ab53dcf6fe4dd5d7a17081aa86a79981b2b7ee`).
Those contracts, including CP1–CP7 and R1–R4, are not replaced by this summary.

## Alternatives

Extending V1 enums in place changes frozen validation and requiredness. Reusing metal-color
questions for material misrepresents their target. Inferring a winner, canonical Unknown or
NotApplicable from an unanswered choice is prohibited. Deleting historical answer flags or
ignoring them globally loses causal evidence.

## Consequences and current implementation boundary

Separate V2 catalog/Rules models reuse the existing registry/interpreter. Source-evidence
classification and availability contracts are internal foundations. They do not yet constitute
an operational F04 clarification lifecycle. In particular, the material-answer/resume paths,
causal durable restoration and description2/IFP3/handoff3/preparation2 integration are not
implemented by this partial change. No functional acceptance or activation is claimed.

Migration `0018_f04_preparation_v2` changes only the preparation-version CHECK to admit 2.0.0.
It neither creates a semantic preparation2 reader nor activates a writer. Downgrade refuses if
2.0.0 rows exist. Migration code and disposable tests are authorized; applying it in shared,
preproduction or production environments requires separate approval. Old rows are not backfilled.

No provider, worker, UI, professional Knowledge content or production configuration changes.
Independent review must not interpret foundation tests as completion of the F04 functional DoD.

## Validation

Existing V1 schema/golden checks, V2 target/category/wording checks, source parsing and negative
authority controls, canonical availability integrity checks, and isolated CHECK migration tests
provide bounded implementation evidence. The Draft PR must report the remaining F04 lifecycle
criteria as unimplemented or not tested, rather than treating these unit tests as HTTP acceptance.
