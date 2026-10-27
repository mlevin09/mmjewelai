# 0032 — Pure canonical preparation and semantic rendering (B1)

Status: proposed implementation record, pending independent B1 review; no runtime cutover.
Date: 2026-10-27.

## Context

The Owner-approved ONE_CANONICAL_PIPELINE R1 design requires a complete immutable preparation
between authoritative enrichment handoff and downstream generation. The legacy compiler cannot
carry active non-schema instructions such as an explicit no-halo prohibition. B1 is limited to pure
contracts/projection/rendering; the currently persisted downstream P1 remains open.

## Decision

Extract the compiler's existing structured revision projection without changing historical output.
Stage IFP/handoff 2.0.0 as pure successor types retaining existing fields plus typed references,
disclosures and the bound description. Retaining the latter permits exact verification of the
existing structured internal formatter without parsing free text or treating the description as
independent authority. No active writer emits these successors in B1.

Preparation 1.0.0 owns canonical bytes, not shallowly frozen nested JSON. It retains complete source,
explicit supplied gate evidence, exact semantic rendering and pointer coverage. Validate nested
hashes, scope/pins, canonical Product State equality, readiness and supported mandatory mappings;
re-render on read. Minimize execution text using stable aliases and omit provenance identifiers
while retaining every original source value internally. Unknown executable meaning fails closed.

Use the R1 domain-separated hashes, exact sorted compact UTF-8 JSON and explicit ID/UTC timestamp
inputs. Keep candidate capacity limits provisional and fail on overflow without truncation.

## Alternatives

- Forward full internal JSON/text: rejected; exposes technical provenance and obscures semantic
  coverage.
- Continue legacy compilation for unsupported sources: rejected; silently loses meaning.
- Rewrite current application writers in B1: deferred to B2/B3; outside this bounded review.
- Shallow Pydantic freeze alone: insufficient for nested mutable JSON; retain owned bytes instead.

## Consequences and validation

No API, worker, provider, database, release activation or deployment changes. Supplied gate evidence
is not authentication/authorization or proof of ACTIVE storage lookup. B2 must obtain the real
transaction snapshot. Historical schemas/hashes remain frozen; image-reference transport/cutover and
full capacity qualification (#118) remain later work. Unit tests cover prohibition/KEEP/locks,
coverage/tamper, history/authority, Unicode, stable IDs, candidate caps and golden legacy parity.

This records the approved R1 implementation slice, not a replacement enrichment architecture.
