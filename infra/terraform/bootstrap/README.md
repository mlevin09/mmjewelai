# Bootstrap stack

This one-time stack creates the versioned, non-public Terraform state bucket, regional Docker
Artifact Registry, GitHub workload identity pool/provider, and the production deployment service
account. It grants explicit administrative roles but never Owner or Editor. The WIF provider accepts
only `mlevin09/mmjewelai` tokens from `refs/heads/jewelai-v2`; pull-request and fork identities cannot
deploy.

Run this manually with an authorized operator identity. Review the plan, then apply only as a
separate post-PR operator action. This repository task must never run `terraform apply`.

The deployer deliberately has no Owner or Editor role. Its explicit bootstrap grants are:

| Role | Terraform use |
| --- | --- |
| Artifact Registry Admin | repository/image metadata management |
| Cloud Scheduler Admin | maintenance schedules |
| Cloud SQL Admin | instance/database/user configuration |
| Cloud Tasks Admin | queue and queue IAM configuration |
| Compute Admin | external load balancer, Armor, IP, certificate, and NEGs |
| DNS Admin | optional records in the supplied zone |
| IAM Security Admin / Service Account Admin / Service Account User / Project IAM Admin | custom roles, runtime identities, and their exact bindings |
| Logging Admin / Monitoring Admin | log metric, dashboard, uptime, and alert policies |
| Cloud Run Admin | services, jobs, and per-resource invoker policies |
| Secret Manager Admin | secret metadata/version and per-secret access policies |
| Service Usage Admin | required API enablement |
| Storage Admin | production bucket metadata/IAM; state object access is separately bucket-scoped |

Runtime identities receive none of these administrative roles. The state bucket uses Google-managed
encryption, uniform access, public-access prevention, versioning, and an authoritative bucket policy
containing only explicit deployer/operator state access. State contains generated sensitive values
and must not be shared or logged. Exact deployment plans use a create-only `deployment-plans/`
object path in this same private bucket, are deleted after the apply attempt, and have a prefix-scoped
one-day lifecycle to purge versioned copies without affecting Terraform state. The bootstrap operator
must include every ongoing operator identity in `operator_members` before applying that authoritative
policy.
