# ADR 0043: Isolated, stopped-by-default CPU LLM lab

- Date: 2026-11-09
- Status: Owner-approved installation; documentation submitted for review.

## Context

The Owner explicitly authorized one real, low-cost GCP VM to install Qwen3-1.7B
Q4_K_M and qualify CPU inference. JewelAI integration is a separate, unauthorized
future task. The existing STT workstream and preproduction platform must remain
unchanged. The approved target is an e2-medium with 4 GiB RAM and a 20 GiB standard
persistent boot disk, below USD 40 per 730 hours.

## Decision

Use one standalone `jewelai-llm-lab` VM in `mmjewellai-preprod/europe-west1-b`,
Ubuntu 24.04 LTS, and the existing default VPC. Manage this isolated experiment
with explicit project/zone-qualified gcloud commands, outside the shared
Terraform state and deployment workflows. Do not import it into either existing
platform stack.

The VM has no service account or API scopes. A dedicated network tag scopes an
IAP-only SSH allow rule and higher-priority ingress/egress deny rules to this VM;
existing shared firewall rules and IAM bindings are unchanged. Instance metadata
blocks project-wide SSH keys. A temporary ephemeral IPv4 address is used only to
download dependencies and checksum-pinned official artifacts, then removed.

Run the pinned llama.cpp CPU binary under a dedicated unprivileged systemd user,
bound to `127.0.0.1:8080`, with one inference slot, 2,048 context tokens, a
one-core CPU quota, 3,000 MiB memory ceiling and no swap. The service has no
outbound network access. Normal prompt/response logging is disabled. Only short
synthetic qualification outputs are explicitly retained as evidence.

Stop the VM after live inference and a full stop/start persistence check. Retain
its boot disk, model, runtime, installer, service and qualification evidence.
The [operator runbook](../operations/llm-lab.md) records exact pins, measurements,
costs, start/verify/stop commands and the private evidence archive.

## Alternatives

- Extending the shared preprod Terraform stack would couple an independent lab
  to active deployment work and require broader infrastructure checks.
- GPU, managed model serving, a load balancer, Kubernetes and larger VMs exceed
  this installation's approved scope.
- Persistent public IPv4 or Cloud NAT adds ongoing cost without a requirement
  for external inference traffic.
- A privileged cloud service account provides no benefit for local inference.

## Consequences

This lab creates no JewelAI endpoint, provider adapter, Parser/Knowledge contract,
application dependency, migration or production deployment. Shared platform
Terraform will not manage the lab; any future integration or ownership transfer
requires a separate approved task.

The on-demand list estimate is USD 27.71 per 730 running hours including the disk;
the stopped state retains approximately USD 0.80 per 730 hours of disk cost.
Model quality and professional jewelry suitability are not qualified: one short
Russian response was grammatically Russian but off-topic. Installation success
does not establish product acceptance.

## Validation

Use the runbook's actual cloud/inference evidence. Repository changes are
documentation-only and require content/link/diff checks, not application tests
or Full Regression. No self-merge or application redeployment is part of this task.
