# ADR 0044: Bounded research campaign MCP controller

- Date: 2026-11-12
- Status: Issue #176 implementation candidate; independent review and live activation pending.

## Current Owner correction — existing Native Runner action, 2026-11-14

PR #177 [coordinator 6874961749](https://github.com/mlevin09/mmjewelai/pull/177#issuecomment-6874961749)
supersedes the status-import blocker below: the Owner/coordinator records an actual
Research Agent `get_instance_basic_info` success. Preserve that managed Compute
connection; it does not expose guest execution. Workspace code execution is supported.

The narrow optional `NativeRunnerActions` composition reuses the existing non-root
SSH/ownership boundary and calls the unchanged `native_llm_bench.runner.execute` on
the guest. The caller chooses hypotheses, eligible sessions and existing numeric
Runner controls. No Controller/Worker, profiles or optimizer is instantiated. The
authenticated MCP exposes catalog, VM status/start/stop, submit, job status and
bounded immutable export reads; never generic shell/file-write tools. Status-only
HTTPS mode remains the default. The opt-in source bundle excludes campaign logic.

Execution requires a host-protected, unexpired Owner approval with spending amount,
start/job/turn/time ceilings and a separately verified guest installation. The
existing 1200-second Compute STOP safeguard, exclusive ownership and append-only
journals remain in force. Dispatch ambiguity consumes its reservation, blocks new
jobs and cannot automatically reissue inference. Guest execution verifies actual
model/runtime file hashes, source/plan pins and a deadline. These ceilings bound
execution; they are not guaranteed dollar billing caps.

This is implemented/tested preparation, **not deployment or Agent-called acceptance**.
The existing private control host has no externally reachable execution MCP endpoint;
its paused Tunnel service is not reused. The optional HTTPS adapter still requires
a real compatible resource-bound OAuth access-token issuer. Existing managed Google
API authorization is not silently repurposed for custom guest execution. No new
issuer, OAuth client, ingress, IAM or server is provisioned here. Qwen remains off;
real installation/inference requires the current run authorization and a reachable,
authenticated Agent execution connection. Local synthetic tests prove neither.

## Current Owner correction — HTTPS read-only connection, 2026-11-14

The Owner confirmed Custom MCP/OAuth support in the existing Agent and selected
HTTPS Streamable HTTP. This supersedes the unimplemented GitHub/Actions alternative
below. The first public slice is only `vm_status`, using official Python MCP SDK
2.3.0 and a separately configured real authorization server. It does not instantiate
the seven-tool `BackendAccess` or read its obsolete Tunnel secret. Existing SSH,
Owner activation, lease and audit behavior are unchanged; no VM starts are added.

The resource server checks signed MCP-audience access tokens, exact issuer, expiry,
client, approved subject and scope before lazy read-only ADC/Compute access. Real
authorization-code/S256 discovery is required at startup. Client registration,
consent and callbacks remain the real issuer's responsibility; no synthetic issuer,
Google ID-token substitution or self-built authorization platform is deployed.
Public metadata and an offline test issuer do not prove live OAuth/Agent access.

The existing product Identity Platform discovery lacks the OAuth authorization/token
and PKCE capability needed for this connection. A compatible registered issuer/client
configuration is the explicit outstanding dependency. No new cloud deployment or
paid resource is created while it is absent. The prepared non-root gateway image
can use separate scale-to-zero Cloud Run with a dedicated instance-GET-only identity;
neither the existing control identity nor any application deployer is suitable.

Dependencies are isolated in the research package's `https` extra: the maintained
official SDK replaces handwritten protocol/auth plumbing for this path; google-auth
provides keyless ADC, PyJWT/cryptography verify public issuer signatures, and Uvicorn
serves ASGI. They are not application dependencies. See
`benchmarks/research_campaign/https/README.md` for exact configuration, hosting
constraints, tests and the remaining live acceptance gate.

## Historical Owner correction — 2026-11-13

Owner rejects all OpenAI Tunnel variants, personal-computer runtime and manual Platform
key handoff. PR #177 comments [6851806625](https://github.com/mlevin09/mmjewelai/pull/177#issuecomment-6851806625)
and [6852026177](https://github.com/mlevin09/mmjewelai/pull/177#issuecomment-6852026177)
supersede the tunnel decision below. Historical source/resources/evidence are retained;
no new resources or tunnel activation are authorized by this correction.

An asynchronous GitHub/Actions read-only status integration may be implemented only after
actual existing Agent GitHub write/read access is established. It must use separately
scoped read-only trust, not the administrative preprod/production deployer or a weakened
deploy-ref provider. Public repository comments are not executable commands. Current
Agent access is unverified because its inspection/run interface is unavailable in the
current session. No claim of Agent GitHub permission denial or connectivity is made.

## Historical Owner directive — simple operational access (superseded)

The final Owner requirement replaces the interim Mac-hosted composition: the connection
must run on a backend independent of both the personal computer and the stopped inference
VM. An isolated, single `e2-micro` control VM with a private NIC, outbound Cloud NAT,
metadata service-account credentials, Secret Manager payloads and systemd supervision is
prepared under `benchmarks/research_campaign/backend`. Research commands still run only
on the original non-root inference account. The control identity can mutate only that
existing inference VM's start/stop lifecycle, not the project or its own infrastructure.
Project-wide permissions are read-only CLI discovery/operation inspection; IAP is scoped
to the target instance's SSH port. Persistent disk retains the ownership journal and
per-authorization start count. No campaign controller is included in the installed bundle.

Alternatives: the interim personal Mac fails the availability requirement; the inference
VM cannot receive its own start request while off; ordinary request-billed/scale-to-zero
application Cloud Run services do not supervise an idle long-polling tunnel. An additional
always-on Cloud Run worker would also incur recurring cost and require durable external
state. A small control VM directly reuses the tested private stdio/SSH boundary without
changing the application. Its additional VPC/NAT cost is explicit in the activation package.

This prepares a new recurring resource and least-privilege IAM/secret metadata; **none is
applied without separate activation authorization**. Secret values never enter Terraform,
the source bundle or logs. Workspace/tunnel association remains an account-side gate; no
claim of per-Agent identity enforcement is made for stdio. Private plugin permissions
must be restricted and assigned only to the existing Agent by the Owner. Local locking
assumes one control host and cooperative external operators, not a cloud-atomic fence.
No new Python dependency, public endpoint, research framework or Benchmark Runner change.

The subsequent Owner instruction supersedes using a campaign controller as the Agent's
connection. The active connection is `jewelai_research.vm_access`: seven infrastructure
tools with scoped non-root guest execution, ownership and automatic runtime shutdown.
Research logic belongs to the existing Workspace Agent. The earlier campaign candidate
below is retained in Git history/source for traceability and is not an activation
prerequisite or part of this connection's runtime. See `benchmarks/research_campaign/VM_ACCESS.md`.

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
