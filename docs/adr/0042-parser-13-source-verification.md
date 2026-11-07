# ADR 0042: Parser 1.3 with version-aware source verification

Status: Owner-approved additive contract; implementation pending independent review.
Date: 2026-11-07.

## Context

Studio recovery reproduced independent labelled fields inheriting preceding negation and a
negative dimension becoming positive. Changing extraction under the existing 1.2 tag would
invalidate source verification of retained sessions. The Owner explicitly approved Parser 1.3
and the smallest additive native Correction/Evaluation evidence-read change, retaining original
1.1/1.2 bytes and hashes, one active Parser, no new API routes and no migration.

## Decision

Every active full-message parse returns 1.3. Explicit recognized RU/EN field headings bound
assertions without severing ordinary negative object lists or dropping component ownership.
Dimension signs are part of source evidence. Non-positive/nonfinite triples cannot create
canonical dimensions; partial triples remain unresolved under the existing atomic Dimensions
contract. No new Dictionary/Knowledge binding, absence transition or professional default is
approved by this change.

The single extractor retains narrowly versioned source-proof rules for old evidence. A private
read-only verifier selects those rules from the immutable record, then compares the complete
parse and deterministic proposal/transition/Matrix to persisted history. Public parsing always
forces current governance, even inside a historical verification scope. There is no client
version selector, duplicated legacy algorithm or legacy write path. Context is request/task
local and reset on exit, including exceptions.

Native F result evidence gains an additive, hash-bound `parser_evidence_version=1.3.0` for new
writes. Historical results omit the field and keep their original serialized bytes/hash.
The marker is needed because initial cycles retain Matrix evidence without a separate parse
DTO. Existing correction tags identify their exact retained source format. Correction3 and
Evaluation3 accept 1.2/1.3 parses; older native readers also retain 1.1 evidence. The unchanged
`f05-1.2` continuation interpreter identifier is not a parser wire-version selector.

## Alternatives

Reinterpreting all historical text with 1.3 breaks valid sessions. Trusting stored hashes alone
or dropping source replay weakens integrity. Duplicating the Parser or exposing a legacy request
selector violates the one-active-Parser decision. A new database column, route or enrichment
model is unnecessary for this additive pin.

## Consequences and validation

Historical data is not rewritten or repaired: an old interpretation remains historical, and a
new supported correction is parsed as 1.3. Tests cover exact historical payload/hash retention,
append-current/restart, source tampering, authority/CAS/tenant protection, explicit field ownership
and signed dimensions. No migration, activation, provider, UI or production configuration change.
Functional acceptance, merge and deployment remain separate coordinator gates.
