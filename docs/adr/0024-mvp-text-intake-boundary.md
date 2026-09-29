# ADR 0024: MVP text-intake trust boundary

- Status: Accepted
- Date: 2026-09-29

## Context

The V2 runtime could accept a manually constructed `ParserCandidate`, but a tester could not begin
with a normal English or Russian jewelry request. Natural-language extraction is probabilistic and
must not gain authority over immutable design state, locks, provenance, or clarification policy.

## Decision

The API persists the original user `Message` before invoking a narrow Google Generative Language
adapter. The adapter makes one bounded, non-retrying request and returns only an untrusted
`ParserCandidate`. It sends raw human terms rather than canonical IDs. The existing deterministic
`ParserProposal` performs target validation, dictionary normalization, ambiguity/unsupported-term
handling, lock protection, and provenance construction.

Accepted proposal changes are applied through the existing revision EDIT transition and database
compare-and-swap boundary. The existing Rules Engine then selects any clarification question; the
understanding model cannot select questions. Prompt compilation and generation retain their current
separate authority and are not part of the extraction adapter.

Preproduction configures the exact text model `gemini-3.1-flash-lite`. The API reads the existing
Google Generative Language key from Secret Manager; credentials never reach the browser. CI injects
a fake provider or mocked HTTP transport and never makes paid calls.

## Alternatives

- Let the model emit canonical design state: rejected because it bypasses dictionary, parser,
  revision, lock, and provenance invariants.
- Put provider logic in `packages/parser`: rejected because the parser is deterministic and
  provider-neutral.
- Require a raw candidate review screen: deferred because automatic application of only accepted
  proposal changes is reversible and still uses every authoritative boundary.

## Consequences

Text Intake v1 supports only existing parser targets and EN/RU session locales. It does not infer
dimensions, create side-stone groups, confirm or lock fields, author prompts, or generate images.
Malformed/provider failures are redacted and fail closed. A persisted message can remain even when
the provider fails, preserving the original user request for audit and retry.
