# ADR 0044: Bounded research campaign MCP controller

- Date: 2026-11-12
- Status: Issue #176 implementation candidate; independent review and live activation pending.

## Context

The approved Research Agent should conduct one outcome-driven, adaptive campaign on the
existing CPU Qwen lab and Native Benchmark Runner, without Owner-managed experiment
microtasks. Its R0 charter currently permits read-only research. It has no configured MCP
execution endpoint, campaign spending amount/period or technically enforceable combined
GCP/Workspace dollar ceiling. The benchmark work must remain isolated from JewelAI runtime.

## Decision

Add an independent `benchmarks/research_campaign` Python package targeting the isolated
benchmark branch. Use seven authenticated MCP tools with strict fields, local operator
activation, source/manifest/model/profile pins and principal scopes. The existing runner
remains unchanged. SQLite append-only hash-chained events and a separate globally locked
worker preserve registered decisions, execution identity, reservations and raw results
across tool/Agent interruptions. Unknown attempts retain their complete reservation and
are never automatically retried. A versioned operator-pinned allowlist defines experiment
types, bounded controls, locale/context samples and exact instruction suffix variants.
The Agent selects treatments without a fixed three-profile grid; derived instruction
runtimes retain separate base/effective hashes and preserve the original source. The Agent selects the next experimental type;
the controller never executes freeform instructions, shell or model-produced commands.

Use standard-library Streamable HTTP JSON responses and an OAuth protected-resource
adapter with a pinned RFC7662 introspection endpoint for future private hosting. A local
Bearer test mode accepts synthetic campaigns only. No generic OAuth authorization server,
cloud platform or new paid dependency is introduced. The only package dependency is the
existing native benchmark runner, installed from its local source.

GCP lifecycle code accepts only the existing fixed VM, describe/start/stop and read-only
operation inspection. Durable leases bind operation, instance ID and start generation;
idle/unowned/ambiguous paths never issue stop or claim verified cleanup. An external
qualified exclusive-use guard must fence actors outside the local store before live use. Private
IAP forwarding reuses existing SSH access without writing instance SSH metadata. Runtime
fingerprints and independent stopped status are checked. All cloud execution remains
disabled in current CLI composition. Live envelopes are rejected: proxy reservations
cannot promise a hard dollar ceiling with delayed billing, retained disks, host failure
and unmetered Workspace credits. Owner must resolve the activation budget/period and
enforceable safety mechanism before a separately reviewed activation composition.

Optional private report delivery uses a campaign/envelope-scoped outbox, approved folder
and permissions, durable preallocated file identity and byte-identical download verification.
No real upload or OAuth acquisition is performed in offline tests. New report payload and
minimum write access require activation approval. The new starter max_tokens=128 differs
from historical A/B/D's 256; equivalence is not assumed. Executable template/EOS changes
remain unsupported; needing them is a product-contract extension, not a live config fix.

## Alternatives

- Generic shell/GCP tools would expose substantially wider authority than this campaign.
- A fixed grid optimizer would replace rather than enable the approved research role.
- Chat-only state would lose reservations and attempted-cost evidence after interruption.
- Rewriting the runner or historical A/B/D artifacts would invalidate reproducibility.
- Treating proxy limits or a budget alert as a hard billing cap would overstate safety.

## Consequences and validation

Offline authenticated HTTP integration proves multiple adaptive choices, deterministic
authorization, budget refusal, crash recovery, immutable evidence and verified fake
cleanup. It does not prove Workspace lifetime/confirmation behavior, live cloud lifecycle
or Qwen quality. Endpoint/tunnel, OAuth/account access, independent supervision and the
Owner's budget activation remain external gates. See the package README for exact setup,
tool contracts, limitations and targeted commands. No application, IAM, shared database,
workflow, production deployment or professional Knowledge changes are included.
