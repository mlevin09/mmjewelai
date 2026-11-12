# Operational VM access — Owner directive, 2026-11-12

This is the active connection entrypoint for **JewelAI — AI Research Agent**.
The campaign controller is not in its execution chain. There are no experiment profiles,
research algorithms, parameter selection or benchmark campaigns in this interface.

## Actual server-side setup

- Existing target only: `mmjewellai-preprod/europe-west1-b/jewelai-llm-lab`.
- GCP-readback confirmed `TERMINATED`, no external IP or service account.
- Configured and read back `scheduling.maxRunDuration.seconds=1200`,
  `instanceTerminationAction=STOP`. This safeguard is enforced by Compute Engine even
  when the Agent, tunnel or local host is unavailable. It is not a dollar billing cap.
- Installed the checksum-verified official OpenAI tunnel-client v0.0.20 on the existing
  Mac. No new paid hosting, public endpoint or IAM grant was created.
- Private server: `~/Library/Application Support/JewelAIResearchVM/serve`.
  It runs system Python independently of Codex. Its source snapshot contains only the VM
  interface and reused infrastructure helpers; it does not load Controller/Worker or
  experiment orchestration. It remains usable while the Qwen VM is off, provided this
  existing Mac is awake/logged in. No claim of availability while that host is powered off.
- Real installed MCP `vm_status` returned the stopped VM and its 1200-second limit.
  A start request without Owner authorization was rejected before any start RPC.

Tools: `vm_status`, `vm_start`, `vm_exec`, `vm_job`, `vm_read`, `vm_write`, `vm_stop`.
Agent chooses commands, scripts and research procedures. Local execution accepts no
arbitrary target/project/SSH user. Guest commands execute as `jewelai-research` without
sudo, GCP credentials, API scopes, forwarded agent or unrestricted project administration.
Files are restricted to its work area and a read-only copy of the existing Runner.
The original Qwen installation, Runner and historical benchmark files are not modified.

Execution is asynchronous so a long VM command does not require a long MCP request.
The non-root helper admits one job at a time, bounds memory/process/output consumption,
and kills a job after 15 minutes. Compute independently stops the whole VM after 20.
Start/stop reuse operation/incarnation ownership proof; an unrelated RUNNING VM is not
adopted or stopped. Host-only authorization records the Owner's spending window/count;
no MCP argument can authorize paid starts or modify that file. Expiry does not disable
owned cleanup. These are infrastructure limits, not experiment policy.

## Remaining non-root bootstrap (requires an approved VM start)

`bootstrap-vm-access.sh` is an operator-only setup script, not an Agent tool. It installs
the root-owned forced-command guest helper and the dedicated account/SSH public key,
with a read-only Runner copy. It must be run only after explicit Owner approval to start
this existing VM. Then verify identity, sudo denial, protected source permissions,
private SSH host key and an actual guest round trip before setting `guest_ready=true`.
Until then the installed server rejects remote execution and Agent-initiated starts.

## Exact one-time OpenAI account connection

No login, Agent URL or new Agent is required from Codex. Account-side configuration must
be performed by the Owner when it is not accessible through authorized tools.

1. In [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels),
   create/reuse a private tunnel named **JewelAI VM Access**, associated with the ChatGPT
   workspace containing the existing Agent. Tunnel operator needs Read+Manage; its
   restricted runtime key needs Read+Use. Do not supply an admin key to the daemon.
2. Run the installed `connect-private-vm-tunnel.py` locally. Enter that tunnel ID and its
   runtime key into the hidden prompt; never send the key in chat. The helper stores the
   key in a separate 0600 file in a 0700 private directory, writes only a `file:` secret
   reference into the profile, runs official client `doctor`, and installs a macOS
   LaunchAgent. No VM is started. The tunnel daemon is not supervised by Codex.
3. In the existing **JewelAI — AI Research Agent**, add a private custom MCP plugin:
   name **JewelAI VM Access**; Connection **Tunnel**; select the same tunnel ID;
   visibility **Only me**. No additional application auth is needed for this stdio
   target: private tunnel access is authenticated by OpenAI account/workspace permissions.
   Do not expose the server through an unauthenticated HTTP URL. Attach these seven tools
   to the existing Agent; do not create another Agent or enable unrelated computer access.

This is a one-time setup flow, not a claim that an unconfigured tunnel can be installed
with one click. Exact remote tunnel ID/health is unavailable until the Owner performs
the account action and supplies the restricted runtime credential through the local helper.

Only after the local runtime is healthy and discovery succeeds, request the one approved
VM-start window for a real connectivity acceptance: Agent start → non-root execution →
one minimal Qwen command → read result → owned stop. No benchmark or parameter study.
READY requires those actual Agent outcomes; local stdio/synthetic tests do not establish it.
