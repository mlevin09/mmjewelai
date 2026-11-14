# Research Agent access — current Owner correction, 2026-11-14

The Owner now selects **HTTPS MCP + OAuth**, initially only read-only `vm_status`.
See [implementation, configuration and actual readiness](https/README.md).
The GitHub/Actions alternative below is superseded and must not be activated.
The new path has no Tunnel dependency. Live deployment and Agent connection remain
blocked on a compatible real OAuth issuer/client configuration, not Agent UI access.

## Historical correction — 2026-11-13

**No OpenAI Tunnel, no Mac runtime, no manually transferred keys.** Owner superseded the
earlier tunnel architecture in [comment 6851806625](https://github.com/mlevin09/mmjewelai/pull/177#issuecomment-6851806625)
and [security correction 6852026177](https://github.com/mlevin09/mmjewelai/pull/177#issuecomment-6852026177).
Do not follow the historical tunnel/key activation procedure below.

The replacement candidate is an authenticated Agent GitHub request, a separably scoped
read-only Actions/WIF status job, and a GitHub receipt. **It is not implemented or active.**
Its prerequisite is proof of read/write through the existing Agent's GitHub app, not the
Codex GitHub connection. Current session has no exposed Workspace Agents inspection/run
tools; discovery did not return a matching plugin, and no authorized Agent UI was available.
Agent-side GitHub availability/permissions remain NOT VERIFIED, not a confirmed denial.
No request workflow or IAM bridge is created before this prerequisite is satisfied.

The protected deploy-ref WIF and privileged preprod/production deployers must not be
reused or widened. No public comment commands, arbitrary shell, paid starts, new recurring
infrastructure or replacement Agent. Existing control resources may remain safely staged.

## Historical implementation — superseded, not current setup instructions

The existing **JewelAI — AI Research Agent** owns research logic. Its seven tools are
`vm_status`, `vm_start`, `vm_stop`, `vm_exec`, `vm_job`, `vm_read`, `vm_write`.
No campaign controller, research profiles or experiment algorithm is in this connection.

## Superseded tunnel runtime

```text
Existing OpenAI Workspace Agent
 → workspace-associated private Secure MCP Tunnel
 → official tunnel-client / systemd on jewelai-research-control
 → existing stdio VM Access server
 → fixed GCP lifecycle / IAP SSH
 → jewelai-llm-lab / non-root jewelai-research / existing Qwen and Runner
```

Prepared backend: one `e2-micro`, Ubuntu 24.04, europe-west1-b, dedicated private VPC/subnet,
no external VM IP and no public MCP/SSH listener. Outbound Cloud NAT reaches OpenAI/GCP.
Only operator IAP SSH ingress is allowed. See [activation package](backend/ACTIVATION.md)
for exact resources, scoped IAM, cost, commands, verification and rollback.

The control host runs while Qwen is off. Neither the Owner's Mac nor Codex participates
in standard runtime. Earlier Mac helpers are historical provisioning artifacts, not the
endpoint. No personal OAuth session is copied to the host.

**Current status (2026-11-12):** Owner authorized activation; control host, scoped IAM,
secret metadata and the runtime snapshot are deployed. Restricted SSH and disabled
activation versions are installed. Real hosted stdio/managed-identity checks pass before
and after control-host reboot. The Mac is not in that execution chain.

The OpenAI tunnel secret still has no versions and no actual tunnel ID was supplied.
The tunnel unit is intentionally disabled/inactive, not running with a fake identity.
Workspace connection and live tunnel reconnection remain NOT VERIFIED. An OpenAI Tunnel
ID plus Read+Use runtime credential/account association are required; a GCP access token
or internal Codex session is not a supplied tunnel credential. No Qwen start is authorized.

## Safety and recovery

- Fixed target only: mmjewellai-preprod/europe-west1-b/jewelai-llm-lab.
- Qwen retains maxRunDuration=1200 and instanceTerminationAction=STOP: a time safeguard,
  not a hard dollar billing cap.
- Starts require an explicit Owner authorization window/count in Secret Manager; initial
  activation is disabled. MCP arguments cannot grant paid access.
- Ownership proofs, audit and per-authorization start counts persist on protected boot
  disk across host/process restart. Never reset state to recover a failed call.
- Recorded starts recover through read-only operation evidence; ambiguous starts never
  retry. Stop submits once, reports STOPPING until the same incarnation is TERMINATED.
- One control host/store only. Local flock and operation/instance/start proof require
  cooperative external operators, not a cloud-atomic fence against administrators.
- systemd reconnects the tunnel after failure/reboot, not experiments or VM starts.
  Secret Manager supplies the restricted SSH key, activation record and Read+Use tunnel
  key to private tmpfs files. Access is rechecked per operation; owned cleanup remains
  available after authorization expiry/revocation.
- Guest user jewelai-research has no sudo/cloud identity. Root-owned forced-command SSH,
  pinned host key, private work area, read-only Runner copy and 15-minute async jobs remain.
- No credentials in Git, Terraform state, argv or logs. Research scripts execute on the
  guest, never the control host. No public HTTP fallback or application/provider change.
- Private plugin/workspace permissions must be restricted by the Owner and attached only
  to the existing Agent. stdio does not independently attest a cryptographic Agent ID.

## Historical evidence — not backend/Agent acceptance

At 16b3452 one separately approved start installed guest restrictions. The old local
backend verified uid 1002 jewelai-research, sudo denial, read-only Runner, a 28-byte file
round trip, and job 05156ca90d324f7ba54d13bece3c4ff2 exit 0. Qwen health returned ok;
no inference or benchmark ran. Bootstrap access was removed, VM TERMINATED, lease RELEASED.
That one-start authorization is consumed. The unchanged guest path reuses this evidence;
it does not prove the new backend or actual Workspace Agent. Source/history is retained.
