# ADR 0039: Prompt Enrichment conversation workspace and read projection

Status: Owner-approved additive read contract; UI implementation for independent review.
Date: 2026-11-05. Assignment: UI-PE-001.

## Context

The existing Web workspace drives legacy evaluation and visualization rather than
Prompt Enrichment. Existing enrichment commands and state3 already support native
L/F and admitted continuations, but no public read exposes the persisted conversation.
Browser storage cannot reconstruct durable user messages, historical questions or
actual decisions. The Owner explicitly approved one minimal read-only conversation
endpoint after this gap was identified. This does not authorize runtime activation.

## Decision

The existing session workspace becomes the Prompt Enrichment entry point. Session
roles/locales come from the existing catalog and are persisted by the unchanged
session command. Existing visualization remains available at the same session's
`/visualization` Web subroute; its implementation and API contracts remain unchanged.

`GET /v1/sessions/{session_id}/prompt-enrichment/conversation` returns a version-1
read projection: session ID, stored user/question/decision events, existing canonical
DesignRevision and existing ContinuationStateV3 (null before initialization).
It uses the existing membership/session scope and scoped history read transaction.
Initialized history is verified through the existing source-verified preview reader
before any transcript is returned. GET creates no records and sets no-store/private.
Raw messages, including unprocessed ones, are labelled stored text, not accepted facts.
Decision outcomes and question wording are copied from existing records. Timestamp,
cycle, kind and stable ID provide deterministic ordering for timestamp ties; this
is a display order, not a new causal or authority ledger. No database migration,
historical rewrite, new writable artifact or new business decision is introduced.

The Web client sends the existing native command versions appropriate to the
session's artifact pins/retained profile. It reuses server frame hashes unchanged.
Admitted workflows use existing version-3 commands; admission and resume are explicit
user actions and only offered when exposed by current server state. Optional answers,
Unknown, Skip and KEEP release use the existing typed contracts. Text is persisted as
Message before submission. A rejected/conflicted request is not automatically replayed;
the draft and stored message remain inspectable while current state is reloaded.

Result inspection uses the real canonical wrappers, state3 description and negotiated
IFP4 with exact If-Match (and the existing explicit L compatibility projection).
Blocked output is reported honestly. KEEP, LOCK, confirmed and explicit/derived/assumed
origins are separate displays of server evidence. The UI never parses text, computes
artifact hashes, accepts a recommendation implicitly or invokes a provider.

## Alternatives

LocalStorage transcripts would lose cross-user/server history and could diverge from
actual decisions. A parallel chat application, client-side enrichment engine, new
message store or new lifecycle contracts are unnecessary. Replacing visualization
with enrichment would discard existing functionality, so it remains a separate route.

## Consequences

The API must already be composed with an explicitly selected verified Knowledge
release; unavailable runtime remains unavailable, with no legacy/provider fallback.
No catalog, continuation capability, preprod or production setting is activated here.
The current server's published description/IFP versions remain authoritative; no
public output5 activation is implied. Transcript loading verifies history and its
latency grows with that existing verification cost; no integrity check is removed.
History reads are currently unpaginated, consistent with existing session history
surfaces. Product/session limits and performance work remain separate scopes.
