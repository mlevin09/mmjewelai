# ADR 0025: Parallel provider visualization iterations and result selection

Status: Accepted for Parallel Provider Iteration v1. Date: 2026-09-29.

## Context

The generation runtime already persists immutable prompt revisions, independent provider
GenerationRuns, private generated Assets, and durable queue dispatch. A tester needs to submit the
same semantic Final Prompt to all active visualization providers, compare successful results, and
record either one contextual selection or an explicit rejection of all results. A provider failure
must not erase successful sibling results or become a global provider ranking.

## Decision

Persist a `visualization_iteration` that pins one session, prompt revision, and prompt content hash.
Each configured iteration-enabled generation profile produces its own existing GenerationRun and
dispatch outbox row linked to that iteration. Runs execute independently through the existing queue,
worker, provider adapter, and Asset materialization flow. Iteration status is derived from member-run
states: pending, succeeded, partial, or failed.

Persist at most one immutable `visualization_selection` decision per iteration. A decision either
selects one READY generated Asset belonging to a run in that exact session and iteration, or rejects
all without deleting Assets. Repeating the identical decision is idempotent; a conflicting decision
is rejected. The session's Current Visual State is the selected Asset from its latest selection
event. This is lineage for the next workflow stage, not editing behavior or a provider score.

The application creates all iteration runs and outbox intents in one database transaction, then
publishes each task independently. Publication failure leaves that run recoverable through the
existing outbox redrive. All providers share the exact persisted prompt revision and content hash;
provider adapters may translate transport only.

## Alternatives

Sequential provider calls, duplicating prompts per provider, selecting a global winning provider,
deleting rejected Assets, storing selection only in browser state, and introducing a separate
orchestration service were rejected. Extending the existing runtime preserves lineage and avoids a
parallel generation or storage path.

## Consequences

The database adds iteration lineage, a nullable backward-compatible GenerationRun link, and an
immutable decision record. Existing single-run APIs remain available. Runtime profile configuration
controls which providers participate through an `iteration_enabled` flag, defaulting to enabled.
Iterative editing, CHANGE/KEEP/LOCKED semantics, analytics, quotas, and provider ranking remain out
of scope.
