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

## Capacity amendment — 2026-11-19 (EN MASTER)

**Context.** The Owner explicitly approved upgrading the same research VM to
`e2-standard-2` and finishing bounded Qwen parameter research. The historical
one-effective-vCPU environment is retained as comparison evidence, not as the
current capacity constraint.

**Decision.** Retain VM ID `8540966569077646041`, its 20 GiB disk, pinned model,
binary, network isolation and lack of service account. Persist `e2-standard-2`
(2 logical vCPUs, nominal 8 GiB) and a separate `CPUQuota=200%` service drop-in.
Keep the existing 2500M/3000M memory high/max and zero-swap limits. Remove the
volatile experimental command override after measurement and stop the VM. Final
readback `2026-11-19T12:25:05.620317+00:00` confirms `TERMINATED` with the upgrade retained.

**Alternatives.** Reverting to e2-medium would contradict the Owner's persistent
capacity decision. Replacing the VM, adding GPU/external model serving, changing
shared IAM/network/Terraform, or activating an application profile is outside this
approved research. Four software threads would not provide four effective CPUs.

**Consequences.** The current compute-plus-disk list estimate is $0.07481136/h,
or $54.61 per 730 running hours; stopped disk storage remains about $0.80 per
730 hours. Continuous running is not authorized. Research selected one inactive
development configuration, `C1-F05-thread2-largebatch-H512`, explicitly **NOT PRODUCT-QUALIFIED**.
No professional Knowledge release, application contract, migration or deployment
is introduced. The [updated runbook](../operations/llm-lab.md) records measurements,
configuration SHA-256, artifact names and limitations. Independent review, merge,
integration and deployment remain separate decisions.

### Перевод RU

**Контекст.** Владелец явно разрешил модернизацию той же исследовательской ВМ до
`e2-standard-2` и завершение ограниченного исследования параметров Qwen.
Историческая среда с одним эффективным vCPU сохранена как доказательство для
сравнения, а не как текущее ограничение мощности.

**Решение.** Сохранить ВМ ID `8540966569077646041`, диск 20 GiB, закреплённые модель
и бинарный файл, сетевую изоляцию и отсутствие service account. Постоянно сохранить
`e2-standard-2` (2 логических vCPU, номинально 8 GiB) и отдельный drop-in службы
`CPUQuota=200%`. Сохранить лимиты памяти high/max 2500M/3000M и swap 0. Удалить
временный экспериментальный override команды после измерений и остановить ВМ.
Итоговая проверка `2026-11-19T12:25:05.620317+00:00` подтверждает `TERMINATED` с сохранённой
модернизацией.

**Альтернативы.** Возврат к e2-medium противоречил бы постоянному решению Владельца
о мощности. Замена ВМ, добавление GPU/внешнего model serving, изменение общих
IAM/сети/Terraform или активация профиля приложения выходят за пределы разрешённого
исследования. Четыре программных потока не предоставили бы четыре эффективных CPU.

**Последствия.** Текущая оценка compute вместе с диском — $0.07481136/h, или
$54.61 за 730 часов работы; диск остановленной ВМ остаётся около $0.80 за 730 часов.
Непрерывная работа не разрешена. Исследование выбрало одну неактивированную
конфигурацию для разработки `C1-F05-thread2-largebatch-H512` с явным статусом **NOT PRODUCT-QUALIFIED**.
Профессиональный выпуск Knowledge, контракт приложения, миграция или deployment
не вводятся. [Обновлённая инструкция](../operations/llm-lab.md) содержит измерения,
SHA-256 конфигурации, имена артефактов и ограничения. Независимая проверка, merge,
интеграция и deployment остаются отдельными решениями.
