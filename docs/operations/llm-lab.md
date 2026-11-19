# JewelAI isolated CPU LLM lab

## Current capacity and R2 research — 2026-11-19 (EN MASTER)

Final readback at `2026-11-19T12:25:05.620317+00:00`: **TERMINATED**, with the approved
`e2-standard-2` upgrade retained. The same VM ID `8540966569077646041` and retained
20 GiB boot disk remain. There is no external IP or service account. The task's
temporary SSH metadata was removed; network and IAM configuration were not changed.

The VM now has nominal 8 GiB RAM and two effective logical vCPUs. Guest topology
reports one core with two SMT threads; this is not a claim of two physical host
cores. The persistent drop-in
`/etc/systemd/system/jewelai-llm-lab.service.d/90-r2-cpu.conf` sets `CPUQuota=200%`;
verified `cpu.max` is `200000 100000` and `nproc` is 2. The existing process limits
remain `MemoryHigh=2500M`, `MemoryMax=3000M`, `MemorySwapMax=0`.

The model and binary pins below are unchanged. The volatile research override was
removed, the original service was health-checked and explicitly stopped, and its
enabled startup setting was retained. The recommended application profile was
**not activated**. The original start/verify/stop commands below remain applicable.

Four identical historical R1 B512 requests were each repeated twice. Historical
full-response p50/p95 were **88.16 / 99.89 s** (n=4); upgraded measurements were
**42.03 / 50.11 s** (n=8), with identical assistant output bytes. This is a measured
52.32% median reduction on that workload, not a controlled causal estimate of the
CPU change. Historical host, date and contention differ; comparator TTFT was not
instrumented.

The bounded study evaluated 16 screening and eight refinement configurations,
then three frozen final candidates. All parameter ranges were sampled, with
explicitly disclosed factor aliasing in the interaction design. Slot erasure
initially returned HTTP 501 before inference; the pinned runtime required
`--slot-save-path`. A separate frozen recovery enabled the erase API only for
cache experiments, using the service's private `/tmp`. Original evidence was
preserved. Synthetic marker checks passed, but the actual concurrent RU/EN pair
took 109.30 s and truncated RU; it did not improve on the 108.51 s serial pair.

| Final candidate | Complete semantic interpretations | Critical category events | Completed typed-valid proposals | Semantic p50 / p95, s |
| --- | --- | --- | --- | --- |
| `C1-F05-thread2-largebatch-H512` | 2/12 | 11 | 12/12 | 60.22 / 74.23 |
| `C0-S00-B512` | 2/12 | 7 | 11/12 | 36.34 / 45.46 |
| `C2-S10-repetition-mid-low` | 2/12 | 8 | 8/12 | 37.55 / 45.89 |

Quality scores are provisional source predicates with actual pinned US-01
Parser/SO replay, not professional gold or independent acceptance. Missing facts,
invalid quotes and malformed/truncated outputs prevent success. Invalid JSON is
not assigned semantic critical categories, so zero categories is not a safety
certificate. The full report includes native R16/D05 source review, omissions,
arbitration decisions, resources, cost and latency-objective failures. A complete
model proposal can still receive SO CLARIFY; the score does not certify a committed
Product State.


The measured US-01 source remains pinned to `bc86a14b3e93d854e034579b459a15cfac899504`. A publication-time read at
`2026-11-19T12:25:59.370076+00:00` found PR #185 at `62c5430e14c0a6970dddfcccaadd938bcc7866b3`. That later revision was not substituted or
qualified by this experiment; parallel development remained unblocked.

The single recommendation is `C1-F05-thread2-largebatch-H512` in
`jewelai-qwen-recommended-config.json`, SHA-256
`69b78a19b1fb54f0a4f2c23237415bba1b64148786907777e311b8900987d492`. It is **NOT PRODUCT-QUALIFIED**. Its principal values are context
8192, threads 2, batch/microbatch
256/128, slots 1,
thinking `true`, reasoning budget
128, and max output 512. The JSON
provides every sampler, seed, timeout/retry, runtime and machine pin; the bilingual
report gives each selection rationale. No global optimum or production SLA is claimed.

Private review artifacts delivered separately:
`JewelAI-Qwen-R2-2026-11-19-Report.html`,
`JewelAI-Qwen-R2-2026-11-19-evidence.zip`, the single configuration JSON, and the
external delivery receipt. Raw measurements and frozen inputs remain under
`/opt/jewelai-qwen-r2-20261119` on the retained disk. Ranking was computed offline after measurement; the final configuration artifact
was written after verified VM shutdown and is delivered locally and through the
approved private evidence destination.

Current regional list estimate: compute **$0.07371546/h**, retained disk
**$0.00109590/h**, combined **$0.07481136/h** or **$54.61 per 730 running hours**.
Stopped disk storage remains about **$0.80 per 730 hours**. These estimates exclude
taxes, discounts and transfer/operator costs; continuous running is not authorized.
Sources: [compute](https://cloud.google.com/products/compute/pricing/general-purpose)
and [disk](https://cloud.google.com/compute/disks-image-pricing).

This repository update is documentation-only. The private standalone research
harness passed 29 local tests and lint checks under the pinned repository policy; that is separate from this PR's
documentation checks and from independent product acceptance. No application,
CI, deployment, catalog or database behavior changed. See the
[capacity amendment in ADR 0043](../adr/0043-isolated-cpu-llm-lab.md).

### Перевод RU

Итоговая проверка `2026-11-19T12:25:05.620317+00:00`: **TERMINATED**, разрешённая модернизация
до `e2-standard-2` сохранена. Сохранены та же ВМ ID `8540966569077646041` и загрузочный
диск 20 GiB. Внешнего IP и service account нет. Временные SSH-метаданные этой задачи
удалены; конфигурация сети и IAM не изменялась.

ВМ имеет номинально 8 GiB RAM и два эффективных логических vCPU. Гостевая топология
показывает одно ядро с двумя потоками SMT; это не утверждение о двух физических
ядрах хоста. Постоянный drop-in
`/etc/systemd/system/jewelai-llm-lab.service.d/90-r2-cpu.conf` задаёт `CPUQuota=200%`;
проверены `cpu.max=200000 100000` и `nproc=2`. Лимиты процесса сохранены:
`MemoryHigh=2500M`, `MemoryMax=3000M`, `MemorySwapMax=0`.

Хеши модели и бинарного файла ниже не изменены. Временный исследовательский
override удалён; исходная служба прошла health-проверку и явно остановлена,
настройка автозапуска сохранена. Рекомендуемый профиль приложения **не активирован**.
Исходные команды запуска, проверки и остановки ниже остаются применимыми.

Четыре идентичных исторических запроса R1 B512 повторены по два раза. Исторические
p50/p95 полного ответа — **88.16 / 99.89 s** (n=4); после модернизации —
**42.03 / 50.11 s** (n=8), при побайтово одинаковых ответах ассистента. Измеренное
снижение медианы на этой нагрузке составляет 52.32%; это не контролируемая
причинная оценка изменения CPU. Хост, дата и конкуренция за ресурсы отличаются;
TTFT компаратора не измерялось.

Ограниченное исследование охватило 16 скрининговых и восемь уточняющих
конфигураций, затем три зафиксированных финальных кандидата. Все диапазоны
параметров опробованы; смешение факторов в плане взаимодействий явно указано.
Первоначально очистка слота вернула HTTP 501 до инференса: закреплённая версия
требовала `--slot-save-path`. Отдельное зафиксированное восстановление включило
API очистки только для опытов с кэшем, используя приватный `/tmp` службы.
Исходные доказательства сохранены. Проверки синтетических маркеров прошли,
но реальная параллельная пара RU/EN заняла 109.30 s и обрезала RU; улучшения
относительно 108.51 s последовательной пары не получено.

| Финальный кандидат | Полное семантическое понимание | Критические события по категориям | Завершённые типизированные предложения | Семантические p50 / p95, s |
| --- | --- | --- | --- | --- |
| `C1-F05-thread2-largebatch-H512` | 2/12 | 11 | 12/12 | 60.22 / 74.23 |
| `C0-S00-B512` | 2/12 | 7 | 11/12 | 36.34 / 45.46 |
| `C2-S10-repetition-mid-low` | 2/12 | 8 | 8/12 | 37.55 / 45.89 |

Оценки качества — предварительные условия исходного текста с фактическим
воспроизведением закреплённых Parser/SO US-01, а не профессиональный эталон или
независимая приёмка. Пропуски фактов, неверные цитаты и некорректные/обрезанные
ответы исключают успех. Неверному JSON не назначаются семантические критические
категории, поэтому ноль категорий не является сертификатом безопасности.
Полный отчёт включает проверку исходных R16/D05, пропуски, решения арбитража,
ресурсы, стоимость и невыполненные цели задержки. Полное предложение модели может
получить SO CLARIFY; оценка не подтверждает зафиксированный Product State.


Измеренный исходник US-01 остаётся закреплённым за `bc86a14b3e93d854e034579b459a15cfac899504`. Проверка перед
публикацией `2026-11-19T12:25:59.370076+00:00` обнаружила PR #185 на `62c5430e14c0a6970dddfcccaadd938bcc7866b3`. Эта более поздняя версия
не подставлялась и не квалифицировалась данным опытом; параллельная разработка
оставалась незаблокированной.

Единственная рекомендация — `C1-F05-thread2-largebatch-H512` в
`jewelai-qwen-recommended-config.json`, SHA-256
`69b78a19b1fb54f0a4f2c23237415bba1b64148786907777e311b8900987d492`. Статус — **NOT PRODUCT-QUALIFIED**. Основные значения: контекст
8192, потоки 2, batch/microbatch
256/128, слоты 1,
thinking `true`, бюджет reasoning
128, максимум вывода 512. JSON
содержит все sampler, seed, timeout/retry, версии runtime и параметры машины;
двуязычный отчёт обосновывает каждый выбор. Глобальный оптимум или production SLA
не заявляются.

Приватные материалы для проверки переданы отдельно:
`JewelAI-Qwen-R2-2026-11-19-Report.html`,
`JewelAI-Qwen-R2-2026-11-19-evidence.zip`, единственный JSON конфигурации и внешняя
квитанция доставки. Исходные измерения и зафиксированные входы сохранены в
`/opt/jewelai-qwen-r2-20261119` на оставленном диске. Ранжирование рассчитано
офлайн после измерений; итоговый файл конфигурации создан после проверенной
остановки ВМ и передан локально и в разрешённое приватное хранилище.

Текущая региональная оценка: compute **$0.07371546/h**, диск **$0.00109590/h**,
суммарно **$0.07481136/h**, или **$54.61 за 730 часов работы**. Диск остановленной
ВМ — около **$0.80 за 730 часов**. Налоги, скидки и расходы на передачу/оператора
не включены; непрерывная работа не разрешена. Источники:
[compute](https://cloud.google.com/products/compute/pricing/general-purpose) и
[disk](https://cloud.google.com/compute/disks-image-pricing).

Изменение репозитория касается только документации. Приватный автономный
исследовательский инструментарий прошёл 29 локальных тестов и lint по закреплённой политике репозитория; это отдельно
от проверок документации данного PR и независимой приёмки продукта. Поведение
приложения, CI, deployment, каталогов и БД не изменено. См.
[поправку мощности ADR 0043](../adr/0043-isolated-cpu-llm-lab.md).

## Historical installation record — 2026-11-09

The following original record is retained for provenance. Its machine/quota and
continuous-running cost describe the initial installation; the current capacity
and research status above supersede those historical values.

Следующая исходная запись сохранена для происхождения данных. Тип машины,
квота и стоимость непрерывной работы описывают первоначальную установку;
текущие значения и исследовательский статус выше заменяют исторические значения.

Owner-approved installation dated 2026-11-09. This is an independent lab, with no
JewelAI, Parser, Knowledge, Studio, provider-adapter or STT integration.
See [ADR 0043](../adr/0043-isolated-cpu-llm-lab.md).

Final cloud readback at 2026-11-09 10:27:49 UTC: **TERMINATED** (stopped), exactly
one VM, retained 20 GiB disk, no public IP or service account, and task-generated
SSH key metadata removed. The local temporary private key was also removed.
The inference service's explicit final stop returned `Result=success`,
`ExecMainStatus=0`, `ActiveState=inactive`. No installer rerun is needed to start it.

## Installed resources

| Item | Value |
| --- | --- |
| Project | `mmjewellai-preprod` |
| VM / retained boot disk | `jewelai-llm-lab` |
| Zone | `europe-west1-b` |
| Machine | `e2-medium`, shared-core, 2 visible vCPUs / 1 effective sustained vCPU, 4 GiB RAM, no GPU |
| Disk | 20 GiB `pd-standard`, `autoDelete=false` |
| OS image | `ubuntu-os-cloud/ubuntu-2404-noble-amd64-v20261105` (Ubuntu 24.04 LTS) |
| VPC / subnet | Existing `default` / `default` in `europe-west1` |
| Network tag | `jewelai-llm-lab` |
| Service account / API scopes | None |
| Public IP / NAT | None after installation; no Cloud NAT or reserved external address |
| Service / user | `jewelai-llm-lab.service` / `jewelai-llm` |
| Listener | `127.0.0.1:8080` |
| Context / inference slots | 2,048 tokens / 1 |
| CPU / memory limits | `CPUQuota=100%`, 2 inference threads; `MemoryHigh=2500M`, `MemoryMax=3000M`, `MemorySwapMax=0` |
| Artifact directory | `/opt/jewelai-llm-lab` on the retained boot disk |

This VM is managed separately with explicit gcloud commands. Neither existing
Terraform state nor the preprod deployment request/workflow was modified. Three
new firewall rules target only the dedicated lab tag: allow IAP SSH at priority
900, deny all other ingress at 1000, and deny egress at 1000. The IAP source range
is `35.235.240.0/20`; inference has no firewall allow rule. Existing broad default
rules have lower precedence. Instance metadata blocks project-wide SSH keys.
The IAP API was enabled; no IAM roles or bindings were added.

## Immutable installation pins

- Runtime release: upstream `v0.9.0`, binary build `b12110`.
- Actual version output: `0.9.0-dev (build 12110, commit cd959bae9)`, GNU 11.4.0,
  Linux x86_64.
- Runtime commit: `cd959bae99ff4bed22bef2604f45241c09bbb8c8`.
- [Official CPU archive](https://github.com/ggml-org/llama.cpp/releases/download/b12110/llama-b12110-bin-ubuntu-x64.tar.gz)
  SHA-256: `368227edcc229be5f9bed16a2223d79b5e41d0ac2e19bcf5825e82291c060e55`.
- Installed `llama-server` SHA-256:
  `eaf9c1c664cc0ae1f4dea4b171bb91aac8409fcfea0574c9b6bcc93792ce2400`.
- Model: `ggml-org/Qwen3-1.7B-GGUF`, `Qwen3-1.7B-Q4_K_M.gguf`.
- Model revision: `daeb8e2d528a760970442092f6bf1e55c3b659eb`.
- [Exact model file](https://huggingface.co/ggml-org/Qwen3-1.7B-GGUF/resolve/daeb8e2d528a760970442092f6bf1e55c3b659eb/Qwen3-1.7B-Q4_K_M.gguf)
  SHA-256: `d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5`;
  size: 1,282,439,264 bytes.

`installed.json` records these pins and the actual installation timestamp.
`install.sh`, `qualify.py`, `runtime-version.txt`, the model and runtime are retained
in the artifact directory. The systemd unit is at
`/etc/systemd/system/jewelai-llm-lab.service`. The CPU runtime uses no GPU backend,
no hosted inference and no API key. Thinking is disabled for these short probes;
the web UI and normal runtime logging are disabled. Systemd restricts the process
to loopback networking, a read-only filesystem and a non-root identity.

## Start, verify and stop

Use the existing authorized Google Cloud identity. All commands identify the
project and zone explicitly; do not change the global gcloud project.

```bash
gcloud compute instances start jewelai-llm-lab \
  --project=mmjewellai-preprod --zone=europe-west1-b --quiet

gcloud compute ssh llmlab@jewelai-llm-lab \
  --project=mmjewellai-preprod --zone=europe-west1-b \
  --tunnel-through-iap --ssh-key-expire-after=1h \
  --command='curl --fail --silent http://127.0.0.1:8080/health'
```

Expected health output is `{"status":"ok"}`. Allow the VM to finish booting and
loading the model; retry the read-only health command if boot is still underway.
The enabled systemd service starts automatically. No installer, model download,
public IP, outbound network or external model call is needed on restart.

For an interactive shell, omit `--command` from the SSH command. On the VM:

```bash
curl --fail --silent http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-1.7b-q4_k_m","messages":[{"role":"user","content":"Write one short English sentence about a cat."}],"temperature":0,"max_tokens":32,"chat_template_kwargs":{"enable_thinking":false}}'

sudo systemctl status jewelai-llm-lab.service
sudo systemctl restart jewelai-llm-lab.service
```

Normal automatic restarts are limited to three starts per 300 seconds, with a
five-second delay. Rapid manual testing also consumes this limit. If a command
fails, inspect `systemctl show ... --property=Result,ExecMainStatus,NRestarts`
and `journalctl -u jewelai-llm-lab.service` first. Only after diagnosing
`start-limit-hit` from intentional manual tests, use `sudo systemctl reset-failed
jewelai-llm-lab.service` before an explicit start; do not mask a real crash or OOM.

From the operator machine, stop when finished and confirm the result:

```bash
gcloud compute instances stop jewelai-llm-lab \
  --project=mmjewellai-preprod --zone=europe-west1-b --quiet

gcloud compute instances describe jewelai-llm-lab \
  --project=mmjewellai-preprod --zone=europe-west1-b \
  --format='value(status)'
```

Expected final status is `TERMINATED` (GCP's stopped-state name). The disk and
installation remain. A pending `STOPPING` is not completion. Do not delete the
instance or disk as part of routine operation. Outbound access is deliberately
blocked; any future dependency/model update needs an explicit maintenance step.

## Observed qualification

Actual CPU inference, not mocks. The final initial probe returned exit code zero.
Only short synthetic requests were used. The recorded warm-cache service start
to successful health check was 3.08 seconds; service restart to health was 3.14
seconds. These are not promises of cold boot latency or sustained throughput.

| Probe | Actual output | Generated tokens | Decode tokens/s | Request wall time |
| --- | --- | --- | --- | --- |
| Russian ring question | `Для ограничения доступа или защиты данных.` | 12 | 4.08 | 6.32 s |
| English sky question | `A clear daytime sky usually appears blue.` | 9 | 4.02 | 4.68 s |
| Independent request after service restart | `The cat lay peacefully on the chair, its paws curled under its body.` | 17 | 4.10 | 6.66 s |
| After full VM stop/start | `Кот сидит на стуле, поглазевая по комнате.` | 21 | 3.84 | 8.87 s |

The first Russian answer is off-topic. Russian generation is demonstrated;
professional jewelry accuracy and product acceptance are **not qualified**.
There was no broad benchmark or application regression suite.

Sampled peak resident memory across the probes was 2,209,804 KiB (2.107 GiB). Per-request CPU usage
was approximately 100% of one core (about half the two visible vCPUs), within the
configured quota allowing normal sampling/burst variation. No swap or kernel
OOM event was observed. Cgroup accounting differs from process RSS because mmap
pages may be charged outside the service; the evidence retains both measures.
After the cold restart the service cgroup peak was 2,298,728,448 bytes (2.141 GiB),
below its 3,000 MiB limit. The actual process UID was 999, not root.

The VM reached `TERMINATED`, restarted, and automatically served the unchanged
model. A new boot ID, identical model modification time, identical installed
manifest and freshly recomputed model SHA-256 prove persistence without reinstall.
The first IAP connection attempted before SSH finished booting failed; the retry
after boot succeeded without a network or security change. The first VM stop
operation took approximately 139 seconds; wait for completion rather than treating
the stop request as a stopped state.

Private access evidence: the live listener was only `127.0.0.1:8080`; connecting
to the guest NIC's port 8080 was refused; an external operator's probes of the
temporary public IP's ports 22 and 8080 timed out; the temporary IP was then
removed and effective firewall rules verified. IAP SSH continued to work.

## Costs

Verified from Google's regional pricing data on 2026-11-09, USD list prices,
before tax, no discounts or free tier assumed:

| Resource | Hourly rate | 730-hour estimate |
| --- | --- | --- |
| e2-medium, europe-west1 | $0.03685773 | $26.9061 |
| 20 GiB standard persistent disk | 20 × $0.000054795/GiB-hour | $0.8000 |
| Persistent public IP / Cloud NAT / load balancer | None | $0 |
| Continuous-running total | $0.03795363 | **$27.71** |
| Stopped, retained disk | $0.00109590 | **$0.80** |

The temporary ephemeral IPv4 rate was $0.005 per attached hour, removed after
installation. Download ingress is free. IAP has no service fee for this usage;
operator traffic can incur ordinary data-transfer charges and is usage-dependent.
There is no steady-state inference egress or fixed networking fee. These figures
are estimates, not an observed billing invoice or a project-wide budget cap.

Sources: [compute](https://cloud.google.com/products/compute/pricing/general-purpose),
[disk](https://cloud.google.com/compute/disks-image-pricing),
[network](https://cloud.google.com/vpc/network-pricing),
[IAP](https://cloud.google.com/iap/pricing). The evidence includes the exact
Belgium-region pricing excerpts, retrieval timestamp and page checksums.

## Reproducibility evidence

The Owner's evidence bundle `JewelAI-LLM-Lab-2026-11-09-evidence.zip` contains 25
members: the exact installer and probe, installed unit/manifest, four synthetic
request results, resource measurements, firewall/VM/disk readbacks, lifecycle
checks, costs, command receipt and a per-file SHA-256 manifest. It contains no
credentials, private keys, model weights or customer data.

Archive size: 30,977 bytes. SHA-256:
`69281b9c705ce1a5c87729fe874dd87d60b830851eff8ec590cd3702c4a5a86a`.
The archive was verified locally and uploaded to the Owner-approved private Drive
destination after explicit authorization. Drive readback confirmed its 30,977-byte
size, destination and existing owner/writer permissions; sharing was unchanged.
The private evidence link is delivered to the Owner outside this repository.
The VM's `/opt/jewelai-llm-lab` also retains the installed scripts and raw synthetic
qualification evidence. Nothing is uploaded to a public evidence host.

The installation is verified; documentation review, any independent product
acceptance, merge and future integration remain separate statuses. No repository
application code or CI/deployment configuration changed.
