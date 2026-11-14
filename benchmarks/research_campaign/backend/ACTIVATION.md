# Historical backend activation package — superseded 2026-11-13

Current direction: [HTTPS read-only MCP](../https/README.md), without Tunnel or
GitHub/Actions workaround. This historical control-host package is not the new
gateway deployment procedure. Its existing runtime/state are preserved.

**Do not activate/configure an OpenAI Tunnel or request its keys/ID.** Owner replaced this
direction in PR #177 [comment 6851806625](https://github.com/mlevin09/mmjewelai/pull/177#issuecomment-6851806625)
and [comment 6852026177](https://github.com/mlevin09/mmjewelai/pull/177#issuecomment-6852026177).
The applied-resource receipts below remain historical evidence, not permission to run
the listed commands now. Existing resources may remain safely staged; no new infrastructure.

The GitHub/Actions status-only alternative is gated on actual Agent GitHub read/write
proof. That is NOT VERIFIED: the current session cannot inspect or invoke the existing
Workspace Agent. Do not substitute Codex's successful GitHub access, loosen deploy WIF,
reuse an administrative deployer, or create workflow plumbing before that gate passes.

Prepared in existing PR #177. Owner subsequently authorized the control-host package,
specified IAM/secrets and deployment. The exact saved plan (18 creates, no deletes/updates)
was applied successfully on 2026-11-12; SHA256
`d4c4df15dbb898171165309e2f2d28e41d0ee58943c9d8bebc844fc36d4574c0`.
This does not authorize a Qwen start or inference. OpenAI tunnel identity/credential and
actual Agent connection remain account-side gates, not satisfied by infrastructure apply.

## Inventory and exact resources

Read-only inspection 2026-11-12: one Compute VM, jewelai-llm-lab (e2-medium, TERMINATED),
no existing Compute router/NAT. Application API/Web/worker/STT are request-driven Cloud Run
services, not isolated continuous tunnel hosts. No suitable existing host was found.

Separate Terraform root `backend/terraform`; never use the application/preprod state:

| Resource | Configuration |
| --- | --- |
| Control VM | mmjewellai-preprod/europe-west1-b/**jewelai-research-control**, e2-micro (shared CPU, 1 GiB), Ubuntu 24.04 LTS amd64 |
| Persistent disk | 10 GiB pd-standard, auto_delete=false; VM deletion/replacement protected; journal survives reboot |
| Private VPC/subnet | jewelai-research-control, 10.203.177.0/28, private Google access, no peering/public VM IP |
| Outbound | Router/NAT of same name, only this subnet; one automatic NAT IPv4 expected |
| Inbound | Operator IAP SSH only, 35.235.240.0/20 → TCP22; OS Login; no public MCP/SSH |
| Identity | jewelai-research-control@mmjewellai-preprod.iam.gserviceaccount.com; metadata ADC, no key JSON |
| Supervisor | jewelai-research-connection.service, non-root jewelai-mcp, restart after failure/reboot |
| State/credentials | durable /var/lib/jewelai-research; volatile private /run/jewelai-research; Secret Manager source |
| Official client | v0.0.20 Linux amd64; verified archive SHA256 2f06ce5a17425c74a827e7038692936e973ae388e7eec728c40efee1fb5f139d |

This root does not manage Qwen, its original model/Runner/history, firewall or 1200s/STOP
settings. No new inference VM, GPU, controller or application deployment.

## Expected monthly cost — estimate, not cap

Budget **approximately USD $12–15/month before tax** for 730 hours and light traffic:

- e2-micro Belgium: estimate $6.7–8/month; reconfirm regional/account SKU before apply.
- 10 GiB pd-standard: approximately $0.40–0.50/month.
- Public NAT one VM: $0.0014/hour × 730 = $1.022/month.
- One NAT IPv4: $0.005/hour × 730 = $3.65/month.
- Three active secret versions: budget approximately $0.18/month plus access calls.
- NAT processing $0.045/GiB, internet transfer, secret calls and private state storage add
  usage charges. Qwen activation/inference is separate. No europe-west1 free-tier claim.

This is not a private billing quote or guaranteed spending ceiling. Account discounts,
tax and actual tunnel traffic are unmeasured. Stopping only the control VM does not remove
NAT/IP/disk charges. Sources: [Compute](https://cloud.google.com/products/compute/pricing/general-purpose),
[disk](https://cloud.google.com/compute/disks-image-pricing), [NAT](https://cloud.google.com/nat/pricing),
[Secret Manager](https://cloud.google.com/secret-manager/pricing).

## Exact runtime IAM (additive, applied under the activation authorization)

1. Custom jewelaiResearchTarget: compute.instances.get/start/stop, bound only to the
   existing jewelai-llm-lab **instance IAM**, never project-wide mutations.
2. Custom jewelaiResearchOperationRead: project-level compute.zoneOperations.get and
   compute.instances.list for documented gcloud IAP discovery. Explicit read-only inventory
   visibility; no setMetadata, project administration, IAM writes or actAs.
3. roles/iap.tunnelResourceAccessor on only that instance's IAP resource, condition
   destination.port == 22. No runtime OS Login administration.
4. roles/secretmanager.secretAccessor on exactly jewelai-research-tunnel-key,
   jewelai-research-ssh-key, jewelai-research-activation. No secret writes or project grant.

Operator provisioning needs existing authorized Compute/network, custom-role/IAM and
secret/version administration plus control-host OS Admin Login and actAs. These operator
privileges are never granted to the Agent. Compute/IAP/Secret Manager APIs must be enabled;
stop on a missing API/permission, do not silently add unrelated authority.

## OpenAI account gate

Owner/admin creates/reuses private **JewelAI VM Access** Secure MCP Tunnel associated with
the workspace containing the existing Agent. Creator: Tunnels Read+Manage. Runtime key:
Read+Use only, not admin. Add via ChatGPT Plugins → + → Add custom MCP server → Connection:
Tunnel; select same ID, restrict access (Only me where available), attach to existing
**JewelAI — AI Research Agent**. No new Agent, login attempt or Agent URL request.

Reference: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
Private stdio does not itself attest an Agent ID; workspace/plugin access must be verified
by Owner. No live discovery is possible without actual account association/key.

## Activation commands — only after consolidated approval

Use any authorized operator workstation/CI shell for provisioning; it is not in runtime.
Verify reviewed commit/clean tree and actual private state bucket name first. The prefix
is research/control-plane, never the application state. Plan files remain private.

```sh
gcloud compute instances describe jewelai-llm-lab --project=mmjewellai-preprod --zone=europe-west1-b --format='json(id,status,scheduling.maxRunDuration,scheduling.instanceTerminationAction)'
terraform -chdir=benchmarks/research_campaign/backend/terraform init -backend-config=bucket=mmjewellai-preprod-tfstate
terraform -chdir=benchmarks/research_campaign/backend/terraform plan -out=control.tfplan
terraform -chdir=benchmarks/research_campaign/backend/terraform show control.tfplan
# Independent saved-plan review: ONLY named control resources and additive grants.
terraform -chdir=benchmarks/research_campaign/backend/terraform apply control.tfplan
```

Stop on any unrelated resource, existing-name collision or permission failure; do not
import/overwrite/replan around it. Do not create a replacement state bucket implicitly.
Secrets are supplied out of band from approved private staging (no values in Terraform):

```sh
gcloud secrets versions add jewelai-research-tunnel-key --project=mmjewellai-preprod --data-file="$PRIVATE_STAGING/tunnel-runtime-key"
gcloud secrets versions add jewelai-research-ssh-key --project=mmjewellai-preprod --data-file="$PRIVATE_STAGING/research_ed25519"
gcloud secrets versions add jewelai-research-activation --project=mmjewellai-preprod --data-file=benchmarks/research_campaign/backend/authorization.disabled.json
```

Use the existing restricted SSH identity whose public key is installed on Qwen; do not
generate a different key and assume access. Its one-time protected transfer to Secret
Manager requires authorization. No private key is in this PR. Supply a verified public
host-key line `jewelai-llm-lab ...` as known_hosts; no untrusted ssh-keyscan or disabled checking.

```sh
python3 benchmarks/research_campaign/backend/build_bundle.py "$PRIVATE_STAGING/backend.tar.gz"
# Set BUNDLE_SHA to printed SHA and TUNNEL_ID to the approved non-secret account ID.
gcloud compute scp --tunnel-through-iap --project=mmjewellai-preprod --zone=europe-west1-b "$PRIVATE_STAGING/backend.tar.gz" "$PRIVATE_STAGING/known_hosts" benchmarks/research_campaign/backend/install.sh benchmarks/research_campaign/backend/jewelai-research-connection.service jewelai-research-control:/tmp/
gcloud compute ssh jewelai-research-control --tunnel-through-iap --project=mmjewellai-preprod --zone=europe-west1-b --command="sudo bash /tmp/install.sh /tmp/backend.tar.gz $BUNDLE_SHA $TUNNEL_ID /tmp/known_hosts"
```

Installer verifies snapshot/client hashes, installs Python/gcloud/OpenSSH and systemd;
no credentials in logs and no Qwen start. Clean only the named non-secret staging files.
The snapshot includes no Controller/Worker, corpus/gold, model or secret. Existing source
and historical benchmark evidence stay unchanged. Backend ADC replaces personal credentials.

If OpenAI account input is not yet available, install everything without a fake identity:

```sh
sudo bash /tmp/install.sh --stage /tmp/backend.tar.gz "$BUNDLE_SHA" /tmp/known_hosts
# Leaves the tunnel service disabled; installs no placeholder backend.json or runtime key.
# After the actual approved tunnel ID/key is supplied:
sudo /usr/local/sbin/jewelai-install-backend --configure "$TUNNEL_ID"
```

The second command configures only the installed backend and enables its supervised
tunnel. It does not reinstall/reset the durable journal, authorize Qwen or run inference.

## Deployment / Agent verification procedure

1. Operator: systemctl is-active/is-enabled jewelai-research-connection.service.
2. Restart service then control host (not Qwen); verify reconnection, unchanged durable
   lease/start count and no inference start. No resetting state to recover failure.
3. Actual existing Agent discovers exactly seven tools; vm_status reads TERMINATED.
   Disabled-window start is rejected, with no start RPC.
4. Only after separate explicit start/inference budget/window authorization: add an
   activation version with exact TARGET, approved=true, integer expires_at/maximum_starts.
   Agent starts once, runs one minimal real Qwen command, retrieves result, stops and
   polls status to TERMINATED/RELEASED. No benchmark campaign or blind retry.
5. Restore disabled activation, verify missing/revoked credential behavior. Save only
   sanitized job/operation/status receipts. Do not publish keys/prompts/provider payloads.

## Safe rollback

Stop/disable backend service, disable activation/tunnel credentials and remove plugin
assignment. Verify Qwen status without adopting an unrelated incarnation; finish an owned
lease's cleanup under its authorization or rely on its existing independent 20-minute
watchdog. Never delete the inference VM or benchmark history.

Operator stops control VM; retains disk/journal and Terraform state (disk charges remain).
Remove only the new runtime identity's target/IAP/secret grants after cleanup. To remove
NAT/IP costs, independently review a new saved plan removing only this root's NAT/router.
No automatic destroy. Deleting protected control VM/disk requires separate retention and
approval; do not erase state to bypass ownership checks. Rollback never restores Mac runtime.

## Honest labels

IMPLEMENTED: backend runtime, unit, staged installer, isolated Terraform and activation package.
DEPLOYED: control infrastructure and runtime STAGED YES; OpenAI tunnel NOT STARTED.
CONNECTED TO AGENT: NO. VERIFIED END-TO-END: NO.

## Actual activation receipts — 2026-11-12

- Exact 18-resource saved plan applied successfully. Control instance ID
  `736794427109435473`, e2-micro, private NIC only, expected managed service account.
- Runtime snapshot from f8e7434b3aa98cadbb22cf202fe38ce8faec7eea:
  22,027 bytes, 12 files, SHA256
  `16d27c259bd6c6cce515d2adc126c55978a3fa57addc3298d18af7884a4edbd1`.
- SSH secret and disabled activation: version 1 ENABLED each. Tunnel secret: zero versions.
  No payload in Git, Terraform state or reports. No OpenAI model key or Codex credential reused.
- Real hosted MCP stdio checks under uid 999 / managed ADC passed before and after reboot:
  exactly seven tools, Qwen TERMINATED, 1200 seconds, unauthorized start DENIED, zero
  start journal records. Managed wrapper fails closed on missing tunnel credential.
- Runtime identity has no get/start/stop/setMetadata authority on its own control VM
  (actual testIamPermissions). No personal OAuth login on the backend.
- One actual control reset operation DONE:
  `operation-1794497580006-6601606ce7e46-ec5b0ff7-fda074e3`.
  Boot ID changed; existing synthetic persistent-state marker hash remained
  `dfea9270e375ca0e57d04af8998a41c1107f92a20bea2cf0e5d01938c5f6cfa8`.
  The rejected initial --async CLI flag submitted no operation; no duplicate reset issued.
- Actual Linux client executes as non-root; systemd-analyze verify passes. Unit remains
  disabled/inactive until real account input. Actual connected-tunnel restart is NOT TESTED.
- Outbound OpenAI HTTPS verified (401 on an intentionally unauthenticated metadata GET);
  this is not an OpenAI credential authentication test or generation.
- Installer fixed the confirmed Ubuntu Snap/apt path mismatch: it now requires the
  actual /usr/bin/gcloud used by the unit. Official apt SDK installed successfully.
- Disposable probe/staging files, synthetic marker and tmpfs probe key copies cleaned.
  Persistent journal directory, managed secrets and installed runtime retained.
- Qwen remained TERMINATED with original lastStartTimestamp
  `2026-11-12T05:13:48.678-08:00`; 1200/STOP unchanged. No inference or benchmark.

Existing GCP authorization was used for provisioning; server runtime uses its own scoped
metadata identity. Neither provides the missing OpenAI tunnel credential. Available tools
do not expose tunnel management/credential minting; plugin discovery did not find an
existing JewelAI connection (not proof that another workspace has none). Do not extract
or copy a hidden Codex session, fabricate an ID, or fall back to a public endpoint.

Remaining single account-setup gate: Owner/admin selects or creates a workspace-associated
tunnel, stores an existing suitable Read+Use runtime key directly as a version of
jewelai-research-tunnel-key, and supplies only the non-secret Tunnel ID. Configure the
installed service with --configure; attach that private connection to the existing Agent.
Do not reprovision infrastructure or reset the lease store to complete this step.

Real Qwen command/owned-lease recovery remains separately NOT TESTED under the no-start
instruction. Unchanged guest behavior reuses earlier 16b3452 evidence, not new live inference.
