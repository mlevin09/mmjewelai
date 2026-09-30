# ADR 0026: Iterative editing uses current-state and immutable visual lineage

- Status: Accepted
- Date: 2026-09-30

## Context

JewelAI can select a generated Asset as a session's Current Visual State, but the original
visualization flow cannot continue that design. An edit such as "increase the center stone by 20%"
must preserve omitted Product State, domain locks, provenance, tenant boundaries, and the selected
private image. Replaying chat history or silently falling back to text-only generation would lose
those guarantees.

## Decision

An `iterative_edit` records the session, starting specification revision, persisted user Message,
and selected READY generated source Asset. The source is resolved from the session's current visual;
clients cannot supply an arbitrary object key or signed URL.

The existing Text Intake authority chain remains authoritative. Provider output is an untrusted
`ParserCandidate`; `ParserProposal`, domain revision transitions, database compare-and-swap, and the
Rules Engine decide what changes. Omitted candidates leave Product State unchanged. Relative
dimension changes are represented as a bounded factor and applied deterministically to an existing
known dimensions value. Existing lock conflicts remain authoritative.

When Product State is READY, the existing Prompt Compiler and visualization fan-out create the next
iteration. That iteration links to the edit, and each worker resolves the source Asset through
scoped persistence. The worker reads the exact private object and verifies its key, MIME type, size,
and SHA-256 before constructing a transient provider-neutral edit input. Signed URLs and image bytes
are not persisted in generation contracts.

Edit-capable adapters must use the reference image. A provider without image-conditioned editing
support rejects the run safely; it must not perform a text-only fallback. Partial-success and
terminal decision gating remain the visualization iteration policy. Successful generated Assets
record the source Asset as their immutable parent lineage.

Runtime state is resolved from Current Product State, Current Visual State, and the new persisted
change request. Historical prompts and outputs remain audit records and are not replayed.

## Alternatives considered

- Replay the whole conversation: rejected because it makes current state implicit and
  nondeterministic.
- Let the understanding provider mutate the revision: rejected because it bypasses dictionary,
  locks, provenance, and CAS.
- Give providers a signed source URL: rejected because URLs are transport credentials and must not
  be persisted when exact server-side object retrieval is available.
- Fall back to text-only generation for unsupported adapters: rejected because it discards the
  selected visual reference while appearing to honor it.

## Consequences

- Iterative edits and visualization iterations have explicit, queryable lineage.
- The prior Asset remains immutable and queryable after a later result is selected.
- Google Generative Language is the initial image-conditioned adapter. OpenAI edit requests fail
  safely until that adapter has an explicit reference-image implementation.
- V1 supports whole-image conditioning only; masks, regional inpainting, visual-difference scoring,
  and automatic verification remain out of scope.
