# ADR 0009: Deterministic provider-neutral prompt compilation

Status: Accepted for Prompt Compiler v1. Date: 2026-09-24.

## Context

Ready immutable specifications need a provider-facing prompt without allowing prompt text or a
template engine to become authoritative business logic. All canonical facts, applicability,
provenance, assumptions, uncertainty, and locks already belong to `DesignRevision`. Future Model
Gateway work requires a verifiable artifact, but no provider integration belongs in this slice.

## Decision

Add `packages/prompts`, depending only on Pydantic and `packages/domain`. Load one explicit,
versioned, declarative prompt artifact; do not scan for latest versions or execute template code.
Compiler code traverses the schema in fixed order, sorts side-stone groups by stable ID, serializes
exact JSON-compatible values, omits absent/Unknown fields, and explicitly represents
`NotApplicable`. It adds no facts, units, translations, assumptions, or provider parameters.

Build specification entries, disclosures, and the locked-constraint manifest from the same validated
revision, then render deterministic English text from those structures. SHA-256 covers the exact
UTF-8 text. Validation recompiles against the exact revision and template and requires complete
model equality, failing closed for changed lineage, entries, disclosures, locks, text, or hash.

The application evaluates the pinned Rules Engine directly and requires `ReadyDecision`; this avoids
the question-event side effect of the evaluate endpoint. Sessions pin the prompt artifact. Alembic
revision `0003_prompt_revisions` adds that pin and immutable prompt revisions. Persistence takes a
row lock and rechecks `current_revision_id` immediately before inserting a prompt revision.

Each successful explicit compile request creates a new immutable prompt revision, even if content is
identical. This records compile events without mutable current-prompt state.

## Alternatives

General-purpose template engines were rejected because v1 needs no executable conditions or dynamic
field traversal. Free-form string lock verification was rejected because substrings cannot prove
manifest completeness. Provider-specific prompts and parameters were deferred to Model Gateway and
generation work. Automatic compilation during revision writes was rejected because readiness and
explicit persistence boundaries should remain observable.

## Consequences

Conversational role and locale cannot change canonical prompt semantics. Derived and assumed values
remain visibly disclosed. References remain logical IDs; no asset is fetched. The initial template is
proposed pending product review and has no claim of aesthetic generation quality. Authentication,
providers, generation, assets, retries, queues, and deployment remain out of scope.
