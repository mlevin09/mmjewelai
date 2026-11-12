# JewelAI research campaign bridge v1

Issue [#176](https://github.com/mlevin09/mmjewelai/issues/176). Research-only;
**not an application service, provider adapter or production dependency**.
PR base is `benchmark/native-llm-stage1`, preserving the Owner's benchmark isolation.

## Delivered boundary

One assignment to the existing Workspace Research Agent → authenticated MCP tools →
append-only hypotheses and registered experiments → durable queue → independent worker →
existing Native Benchmark Runner → immutable raw evidence → agent evaluates the evidence
and chooses a different experiment type → bounded stop → one verified campaign report.

No new optimizer replaces the Research Agent. It chooses the next hypothesis, profile and
authorized sample based on results. The controller enforces permissions, provenance,
limits and execution. Agent interpretations remain explicitly unverified research claims;
professional gold remains `REVIEW_REQUIRED`. No S/T/K winner is certified automatically.

The offline E2E uses real authenticated HTTP MCP calls, the real runner/journal, a synthetic
reasoning driver, fake lifecycle and synthetic inference. It explores three experiment
types, consumes five actual attempts against six reserved attempts, reaches the hard
reservation ceiling, verifies shutdown, restarts readers and emits one immutable report.
This **does not** verify a Workspace Agent's lifetime, tool confirmation settings, real
Qwen quality, GCP shutdown or billed-dollar enforcement.

## Tools and authorization

MCP Streamable HTTP `/mcp`, protocol negotiation `2025-03-26`, `2025-06-18`, `2025-11-25`;
JSON responses, no unsolicited SSE, no per-connection state. GET `/mcp` returns 405.
`initialize`, `ping`, `tools/list`, `tools/call`, initialized/cancelled notifications.
Cancellation of an MCP request is **not** a campaign stop: use `stop_campaign`.
Tool input schemas are generated from `mcp.tool_schema()`; all reject extra arguments.

| Tool | Scope | Behavior |
| --- | --- | --- |
| `campaign_status` | `campaign.read` | Pins, limits, authorized profiles/sample, states, cleanup |
| `propose_and_register_experiment` | `campaign.execute` | Hypothesis, alternatives, rationale, falsification and prior experiment references; reserve worst-case cost |
| `execute_registered_experiment` | `campaign.execute` | Queue only; fast response, no inference in HTTP/SQL transaction |
| `get_experiment_results` | `campaign.read` | Terminal receipt, raw runner data and measurements; verify stored hashes |
| `list_ledger` | `campaign.read` | Paginated immutable hash-chained events |
| `finalize_campaign` | `campaign.execute` | All work terminal + independently observed stopped status; one private report |
| `stop_campaign` | `campaign.execute` | Durable emergency stop; current bounded request can finish, subsequent requests forbidden; worker verifies cleanup |

Every call is bound to the envelope's exact authenticated subject, not a user-supplied
identity. Mutations require an idempotency key: same request replays the original receipt;
different request with the same key fails closed. A replayed QUEUED response does not enqueue
again. Read `campaign_status` for current state. No tool creates/activates a campaign,
changes permissions, writes gold, accepts a command, a path, an endpoint, a VM or freeform
system instructions. Hypothesis text is audit-only and never executed or used as a prompt.

Serving binds **only `127.0.0.1`**. Host, Origin, protocol, content type, request size and
Bearer identity are validated; access logs are disabled. Default local bearer mode is
restricted to synthetic envelopes. Remote use requires a separately configured OAuth 2.1
authorization server and reviewed HTTPS gateway or Secure MCP Tunnel. The resource-server
adapter uses a **pinned HTTPS RFC7662 introspection endpoint**, checks active, issuer,
resource audience, expiry, subject and scopes, refuses redirects and fails closed on error.
It never forwards OAuth tokens to GCP/Qwen. OAuth client secret stays server-side in env;
do not place credentials in a campaign file, tool argument, URL or Git.

## State, recovery and immutable inputs

Private local POSIX store (0700 directory, 0600 SQLite DB); not shared NFS or a new cloud
database. SQLite FULL synchronous transactions append hash-linked events; update/delete
triggers reject changes. Projections are reconstructed from the ledger, not chat memory.
Global worker flock permits one execution per store across campaigns. Use exactly one
store/worker deployment for the one permitted VM. External tools cannot select a new store.

Inputs pin canonical runtime corpus, manifest, **actual source-file byte hashes**, existing
runner source hash, controller source hash and sealed profile registry hash. The optional
evaluator file is hashed only; never parsed, rewritten or passed to inference. Selection
checks both corpus holdout flags and the eleven reserved question IDs plus their grouped
sessions, including IDs of individual turns. Existing Stage 1 A/B/D artifacts are never
opened for write, renamed, regenerated or included as a native baseline for new research.

Before execution the worker records a scoped run identity and claim. The unmodified runner
fsyncs request records before I/O and keeps raw responses. A killed/interrupted attempt
retains its full cost reservation. Recovery marks the experiment `UNKNOWN` and **never
automatically reissues inference**. A separately registered follow-up is a new charged
decision under the same campaign limits, with explicit evidence referencing the unknown
experiment. Timeout is terminal for that attempt. Runner `max_attempts=1` intentionally
prevents hidden retries. Recovery validates raw history, hashes, instructions and scope.
If evidence is corrupted, recovery fails closed but still attempts verified shutdown.

SIGTERM is handled by the worker CLI and cleanup runs before exit. SIGKILL/host loss cannot
execute Python cleanup: an external supervisor must restart the worker, which reconciles
RUNNING claims and stops the VM. **No claim of an independent cloud watchdog or exact
hard billing cap is made.** Current live activation is blocked for this reason too.

## Sealed experimental space v1

| Profile | Type | Difference from control |
| --- | --- | --- |
| `NATIVE_CONTROL_V1` | native control | Unchanged original role/neutral system instruction; temperature 0 |
| `SAMPLING_LOW_TEMP_V1` | sampling | Temperature 0.2 only |
| `BREVITY_POLICY_V1` | policy/template research | Existing runner's exact sealed NB09D suffix, separately hashed and labelled |

All use existing Config defaults: context 2048, top_p=1, top_k=40, max_tokens=128,
repeat_penalty=1, no thinking/cache, timeout ≤60s. Inference seed and scheduling seed
are independent envelope fields. Every profile and effective instruction is recorded and
hashed by the runner. No model weights, arbitrary prompt overrides, role prompt replacement
or template executor are introduced. More research profiles require a reviewed code change;
this finite space lets the Agent choose **experiment types**, not only numeric grid points.

## Budget and activation: live is fail-closed

An operator-only envelope binds version, campaign/assignment, principal, exact target,
input/source/profile hashes, sample, profiles, seeds, explicit start/end period,
max wall-time/experiments/turns/attempts and integer budget reservations. It is imported
locally, **not accepted through MCP**. The private host/operator is the trust root; a hash
records authorization scope but is not claimed to be an Owner digital signature.

Reservation = lifecycle + retained disk + Agent usage reserves + full worst-case attempt
cost for every registered experiment. Unknown/timeouts/blocked later turns do not refund
it. Soft-limit warning is exposed in status; the hard reservation cap rejects further
registration atomically. Deadline is checked before start and every I/O; request timeout
is capped to remaining wall-time. VM start/stop and disk/Agent reserves are explicit,
not hidden as zero-price inference.

**These are conservative proxy units, not an enforceable dollar cap on GCP billing or
ChatGPT credits.** GCP billing lag, ongoing retained-disk costs, host loss and inaccessible
Workspace spend mean there is currently no exact combined hard-ceiling mechanism.
`mode=LIVE` therefore fails unconditionally with
`live_activation_blocked_budget_and_workspace_authorization`, even if freeform envelope
text claims Owner approval. A synthetic envelope accepts only synthetic runtime artifacts
and `NO_PAID_CALLS`. No operator budget amount or period is fabricated.

Before live activation, Owner/Coordinator must settle one consolidated activation package:
amount **and period**, Agent usage accounting/limit, accepted enforceable guarantee and
independent shutdown/supervision, private host/tunnel + OAuth identity, exact pinned
nonholdout sample/profiles, and the one controlled activation test. Approving proxy units
alone cannot remove the live gate. The corresponding reviewed activation composition is
not silently deployed by this PR.

## Existing GCP path (implemented, fake-tested, NOT live-qualified)

Only `mmjewellai-preprod/europe-west1-b/jewelai-llm-lab`, e2-medium CPU, no service account,
GPU or public interface. `GcpLab` permits fixed describe/start/stop argv only, no shell or
IAM mutations. Default permit is false. Only a future reviewed composition can supply it;
the current CLI cannot activate live mode or select a live worker.

`PrivateTunnel` reuses existing operator IAP+SSH authorization: `gcloud compute
start-iap-tunnel ... 22 --listen-on-stdin` as a fixed SSH proxy, existing private key,
preverified known_hosts, strict host-key checks. It does **not** call `gcloud compute ssh`
or add instance SSH metadata/keys. Fixed remote read-only attestation hashes actual pinned
model and binary files before forwarding loopback 8080, then checks health. No raw command
output enters tools/logs. Cleanup closes the local tunnel and issues stop, then polls the
independent VM status until TERMINATED; failure remains `verified_stopped=false` and
prevents finalization. IAM denied/SSH identity unavailable must be reported, never repaired
by broadening grants. Remote runtime flags and the supervised hosting lifecycle must be
qualified in the separately authorized live activation; fake tests are not that evidence.

## Offline installation and reproducible execution

Requires Python 3.12+, POSIX flock and SQLite. Only runtime dependency is the **existing
local runner**; no cloud/auth/model SDK, OpenAI key or new paid service is installed.
From repository root:

```sh
python3 -m pip install -e benchmarks/native_llm_stage1 -e benchmarks/research_campaign
python3 -m pytest -c benchmarks/research_campaign/pyproject.toml benchmarks/research_campaign/tests -q
python3 -m ruff check benchmarks/research_campaign
python3 -m ruff format --check benchmarks/research_campaign
```

The HTTP tests use loopback sockets only (sandbox approval may be required). The real GCP
driver is injected with fake subprocesses in tests, not invoked against cloud.

For interactive synthetic tools, set a strong random `JEWELAI_RESEARCH_LOCAL_TOKEN` in the
server environment without printing it. Use a private `/tmp` directory outside Git:

```sh
jewelai-research init-synthetic --store /tmp/jewelai-campaign-private \
  --corpus benchmarks/native_llm_stage1/fixtures/synthetic.runtime.json \
  --manifest benchmarks/native_llm_stage1/fixtures/synthetic.model.json
```

Start `serve` and `worker` with the same `--store`, `--corpus`, `--manifest` and campaign;
`serve` listens on `http://127.0.0.1:8765/mcp`. It requires that local token. This loopback
URL is **not a remotely retrievable Workspace server**. Repeated tool calls and MCP
connection loss do not erase the queue/ledger. `report` verifies the immutable report
hash. Keep the private store and outputs out of Git.

## Exact Workspace connection handoff

Read [official Custom MCP documentation](https://developers.openai.com/api/docs/guides/custom-mcp-server)
and [OAuth guidance](https://developers.openai.com/plugins/build/auth), not a guessed
"GCP connector". In ChatGPT web Plugins → Add custom MCP server, choose the approved
HTTPS `/mcp` URL **or** Secure MCP Tunnel, configure OAuth with the approved issuer/client,
review the warning, create/install privately, then attach only this plugin to the existing
**JewelAI — AI Research Agent**. Account Developer Mode/workspace approval and custom-tool
confirmation policy must permit the reviewed campaign; never bypass organization policy.
Discovery is authenticated; choose OAuth, not mixed/no-auth. Protected-resource metadata
is served at `/.well-known/oauth-protected-resource/mcp`. External gateway must preserve
the pinned resource identity and forward the allowed Host; do not trust forwarded headers.

**Actual remote URL / tunnel ID: NOT PROVISIONED. OAuth issuer/client: NOT CONFIGURED.**
No relevant Workspace management/tunnel tool is available in this development session.
The connected GitHub/Drive sources do not grant Workspace tool installation or GCP actions.
After deployment is explicitly authorized, record the real URL/issuer and complete **one**
bounded connection+activation action: install the plugin, authenticate the approved subject,
discover seven tools, resume the designated campaign, prove >1 evidence-led experiment
choice, budget stop, cleanup and final report. Until then real Workspace autonomous
continuation/confirmation behavior is **NOT VERIFIED**. The durable worker survives
accepted jobs; it does not invent a new Agent decision when Workspace reasoning is offline.

Suggested instruction addition for the existing Agent (activate only after authorization):

> For this single campaign assignment use campaign_status first. Review existing evidence,
> write competing hypotheses, choose an authorized experiment type/sample, register and
> execute it, then inspect results. Adapt the next type to observed evidence; do not follow
> a predetermined grid. Poll rather than resubmit unknown work. Continue within the one
> activation envelope without Owner micro-prompts. Stop at budget, deadline or safety
> uncertainty, verify cleanup, and finalize one report. Preserve professional REVIEW_REQUIRED
> and distinguish measured facts, hypotheses and Owner decisions. Never request shell,
> gold writes, holdouts or new cloud permissions.

## Private report publication

`report.json` is the single immutable self-contained campaign artifact with receipt hashes,
verified raw evidence, measured counts, decisions, limits and cleanup. No automatic Drive
upload is enabled. Existing intended private destination is Benchmark folder
`1AQzcmYZJNRpPHx-PktnKGEBhZ7FKt9cj`. Only after explicit minimum write permission and approval
of that exact new payload may the connected publication tool upload it; read back bytes
and verify SHA-256/size before sharing the private link. No public sharing, automatic
credential acquisition, gold publication or Drive fallback to runtime inputs.
