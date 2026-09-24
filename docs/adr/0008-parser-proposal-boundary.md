# ADR 0008: Parser proposal trust boundary

Status: Accepted for Parser Proposal v1. Date: 2026-09-24.

## Context

The runtime needs to turn future provider output into a candidate design update without allowing a
model, prompt, or HTTP caller to define canonical domain state. The existing Design Schema owns
state/provenance, the Domain Dictionary owns terminology, revision transitions own lock semantics,
and persistence CAS owns concurrent acceptance. A parser boundary must compose those contracts
without duplicating them or making provider behavior authoritative.

## Decision

Add `packages/parser` as a provider-neutral deterministic package depending only on Pydantic and
`packages/domain`. It accepts an immutable, strictly allowlisted `ParserCandidate` and builds a
`ParserProposal` against one exact `DesignRevision`, `MessageSource`, resolved EN/RU locale, and
pinned dictionary registry. It performs no network calls, prompt execution, persistence, Rules
Engine selection, or Question Catalog rendering.

Candidates contain typed values, not domain state wrappers. They cannot set provenance,
confirmation, locks, assumptions, derivations, unknown values, or applicability. Dictionary-backed
terms resolve with an explicit target category. Ambiguity, unsupported terminology, deprecated
entries, locked conflicts, and unknown side-stone groups are typed deterministic issues. Deprecated
aliases may resolve to an active canonical ID only with a visible warning.

Accepted changes become unconfirmed, unlocked `Explicit` states sourced from the persisted user
message. Omitted fields and already-equal values preserve their exact prior state. Different locked
values are never overwritten. Numeric values use the existing Schema v1 types and units; no unit
conversion or gemstone dimension inference is allowed.

Persist bounded user messages in the runtime through Alembic revision `0002_parser_messages`. The API
binds proposal creation to a message in the same organization-scoped session. It returns proposals
without mutating the current revision. Acceptance remains an explicit EDIT transition followed by
database compare-and-swap, so a proposal based on an old revision cannot overwrite newer state.

## Alternatives

Allowing providers to emit complete `Design` or `DesignRevision` payloads was rejected because they
could forge provenance and lock state. Embedding parser behavior in FastAPI routes was rejected
because it would make deterministic acceptance framework-dependent. Persisting proposals as
canonical revisions automatically was rejected because proposals are untrusted and may contain
typed issues requiring review. Fuzzy matching and model-driven normalization were rejected because
they are nondeterministic and can collapse jewelry meanings.

## Consequences

Provider adapters and extraction prompts can be added later without changing the acceptance
contract. They must submit candidates through this boundary and remain untrusted. V1 supports a
bounded set of scalar center-stone/metal/design targets plus quantity on an existing side-stone
group; arbitrary paths and side-stone creation remain unsupported. Message retention, redaction,
assistant messages, authentication, and provider invocation remain future work.

## Validation

Run the parser schema drift test, parser unit suite, complete domain regression suite, runtime/API
suite, Alembic upgrade/check/current commands, and Ruff lint/format checks documented in package
READMEs and the Runtime API workflow.
