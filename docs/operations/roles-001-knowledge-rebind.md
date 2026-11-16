# Issue #182 — immutable ROLES-001 preprod consumer rebind

## EN MASTER — verified packaging, not deployment acceptance

Baseline: `ceef39a89f00935f30a91141ace5b25ceeca68cd` (`jewelai-v2`, request #33).
[Failed deployment 43918833819](https://github.com/mlevin09/mmjewelai/actions/runs/43918833819)
failed in the image verifier before Terraform apply/migration. Its actual Environment
pin matched the original archive below. No deployment was executed by this task.

The old manifest selected Questions/Rules `2.0.0`; dictionary, parametric, prompts
and historical roles version markers were `1.0.0`. Those exact version pins remain.
ROLES-001 changed both checked-in Question versions, but this release uses v2 only.
The original archive reproduces `Consumer artifact bytes do not match the integration manifest`.
All actual consumer identities were compared, rather than assuming a Questions-only delta:

| Consumer | Current file SHA-256 | Compared with original envelope |
| --- | --- | --- |
| dictionary | `0a7f9f230b6566bb7aca7df4ebe1ab94b66c5a9cd0df8f7635c2b055c92397e9` | unchanged |
| knowledge_base | `7e968f0cba17020eb6bfc520be5a9be7b0672f7d51c6c97339c07cc471a95d31` | unchanged |
| prompts | `9ab6b72d52931a5efe43233202e07850c5543bd327876e00bab80879c32b2f7d` | unchanged |
| questions | `2fde26801816bfa00982aeeb871a54666ebae17bec3ed761901c007b6e2e1474` | changed |
| roles | `not a file consumer` | changed |
| rules | `c73a131e7dcfcf67cb921879ffeaa575a34f6c5d61877d31fa381d1d1c21be9c` | unchanged |

Historical `roles` file metadata is removed from the consumer list, as already
required by the merged verifier. It is not replaced with an old Role JSON catalog.
Current PostgreSQL role validation, sessions and migration 0021 are unchanged.

### Immutable artifact and exact selection

- Package `jewelai.preprod.recovered_core/1.0.0`, contract `1.1.0`.
- Runtime identity: `dca0d4ae27155552745072a818f37a741be5983711ffbab834e198357133de57`.
- Validation report identity: `c3260a3e86dba45f796fb6db1004fc07384fe9e20310623cbba519fff52da12c`.
- Counts/provenance/explicit gaps retained: 392 semantic / 584 parametric / 21 dictionary.
- Original object SHA-256: `240a5d3b4bf8bc55e4e98e0364d06b987c67f4c4956c2102af835b1f2ab0fbfb`;
  generation `1793886431773971`; original object was not overwritten.
- New object: `gs://mmjewellai-preprod-tfstate/knowledge-releases/preprod/dca0d4ae27155552745072a818f37a741be5983711ffbab834e198357133de57/6f6d9b114efbdb923795f4f10776dc2a89b00e293d551a6e0c07a020e3395e6a.zip`.
- New generation: `1794851467699526`; 35027 bytes.
- New archive SHA-256: `6f6d9b114efbdb923795f4f10776dc2a89b00e293d551a6e0c07a020e3395e6a`.
- Download/readback compared byte-for-byte with local output: PASS.
- Bucket public-access prevention enforced; uniform bucket-level access enabled.
- Only `consumer_artifacts` differs in the integration-manifest JSON. All other
  fields and the following six actual member bytes remain unchanged. File-byte
  hashes below intentionally differ from canonical domain identity hashes.

| Preserved member | File SHA-256 | Result |
| --- | --- | --- |
| `active.json` | `a9fa65ce5679fb5d169b4764c24fc049ab71c52e4369c1b63622223df0412597` | byte-identical |
| `knowledge/jewelai.preprod.recovered_core/1.0.0/checksums.json` | `9bbc9323754e49577ca208744ea355a55fd4f55348d916d46700b49c41b88d6e` | byte-identical |
| `knowledge/jewelai.preprod.recovered_core/1.0.0/manifest.json` | `44f1eb42cb1954cdc15644bd3723ed0bebdeeb267eef90296fa5c6cd7fb66187` | byte-identical |
| `knowledge/jewelai.preprod.recovered_core/1.0.0/runtime.json` | `a4c5fbaa132e388fc3ba24f563e1577bc4e328f11a087ee9332d86efecf6364a` | byte-identical |
| `knowledge/jewelai.preprod.recovered_core/1.0.0/source.json` | `ede90fe7418f24955f60f47e0952d49db1760db5af8a61a7d69c6d823a161a0b` | byte-identical |
| `validation-report.json` | `3b67daa38e37c2e4432f8cef7ae3052f2e1cd0d7c6b1bd25109d6fb2461c39ac` | byte-identical |

The existing preprod Environment variable `PROMPT_ENRICHMENT_RELEASE_JSON` was
updated to the exact [reviewable selection JSON](../prompt-enrichment/preprod-knowledge/roles-001-release-pin.json)
with HTTP 204 and matching GET readback, at `2026-11-16T17:53:21Z`. No active preprod
workflow was present at the change. No repository-wide or production variable,
workflow, IAM, secret, role seed, database or schema was changed.
The workflow's historical fallback is unchanged; the Environment override is the
existing operational configuration mechanism. Rollback is the original eight-field
selection tuple, not deletion or alteration of either archive.

### Tool and focused validation

`tools/knowledge/rebind_preprod_integration.py` consumes the original archive and
its exact config. Existing `fetch_preprod_release.unpack()` enforces archive SHA,
exact seven members, selection and path safety. The tool changes only consumer hashes,
loads exact pinned consumers and calls the unchanged `verify_preprod_integration.verify()`.
That verifier loads/recompiles the real store, checks ACTIVE/report identity, typed
parametric runtime and recovered-component hashes. No publish/promote API is called.
It writes a deterministic new archive only after successful validation and refuses
an existing output. This is compatibility packaging, not new semantic qualification.

```sh
python tools/knowledge/rebind_preprod_integration.py \
  --archive /private/original.zip --config /private/original-pin.json \
  --output /private/new.zip --repository-root .
python tools/knowledge/verify_preprod_integration.py /private/unpacked-new --repository-root .
python -m pytest -c apps/api/pyproject.toml apps/api/tests/test_professional_release_transport.py -q
```

Native API transport/rebind tests: 18 PASS in 4.13s before the additional exact-pin
consistency test (1 PASS in 0.48s). New tests then moved to their own module, leaving
the original transport module and historical scaffold unchanged: 10 PASS in 3.88s.
Final combined transport/rebind: 19 PASS in 4.10s. The previously failing Roles
ownership reference then passed alone (1 PASS in 11.49s). Earlier 63 PASS receipts
are retained as checkpoint evidence, not relabelled as final-head CI. Positive coverage includes stale-to-current consumers,
all six preserved members, manifest-field equality, deterministic ZIP, no overwrite,
and real qualification. Negative coverage includes checksum, ACTIVE, report, runtime,
recovered components, typed parametric runtime, consumer bytes and manifest hashes.

No local Docker is installed. Build-only qualification instead used the existing
Cloud Build API in the same preprod project, with no new IAM/infrastructure or
registry image publication:
[build ac9c494f-cedb-436a-a8d6-2f277c17bbf9](https://console.cloud.google.com/cloud-build/builds;region=europe-west1/ac9c494f-cedb-436a-a8d6-2f277c17bbf9?project=483253159059).
Actual start/finish: `17:48:39`–`17:49:44 UTC` (64.3 seconds).

| Actual Docker check | Result |
| --- | --- |
| Existing `infra/docker/api.Dockerfile`, exact current API/package/data sources | VERIFIED PASS |
| Existing preprod overlay, original `RUN python .../_verify.py ... --repository-root /app` | VERIFIED PASS / QUALIFIED |
| Wrong consumer hash in copied manifest | VERIFIED PASS: build rejected with expected consumer mismatch |
| Modified actual Questions v2 bytes in base image | VERIFIED PASS: build rejected with expected consumer mismatch |

Build source: 313 explicitly included files (runtime source/packaging, data/specs,
migrations and isolated qualification contexts), 980,913-byte tar.gz, SHA-256
`a80bf792ac5c25cc3b2f5b031516baf401b9d0d0d6c96aa77d42865d40b9cb1a`, retained privately
under `knowledge-releases/preprod/issue182-builds/` in the same protected bucket.
The Cloud Build request retains all exact build commands. Runtime source did not
change after this qualification; this PR changes packaging, tests, ownership metadata
and documentation only. A fresh deploy must still build and verify its merged SHA.

Test ledger: one initial transport command was stopped after a newly written test
helper included its own ZIP during member enumeration (~3 minutes, 9 cases complete).
The helper now snapshots members before creating the archive. Its sole disposable
incomplete file was deleted. One corrected transport run passed; no repeated full
API suite, Full Regression, provider request or HTTP/customer-data mutation occurred.
The initial ownership-test batch reported 63 PASS / 1 FAIL (26.69s): replacing a
historical helper-hash pair broke its frozen Roles reference. That change was reverted.
A single-case rerun exposed a missing new-test target in the historical tree (1.59s);
the new tool now has its own complete ownership scope, retaining the original Roles
component and source pairs. Only that failed case was rerun after correction.

CI ownership assigns the new tool/pin to a focused release-rebind component with
complete native transport/rebind test modules. The existing release-verifier ownership
and historical test-support hash contracts remain unchanged. Gate implementation,
fixture safety and mandatory coverage are unchanged. Hosted CI is separate evidence in the PR;
local/build PASS does not claim independent acceptance.

### Coordinator handoff / explicit remaining gates

Codex supplies the immutable archive/pin and focused tool PR; coordinator owns review,
merge, deployment and actual preprod acceptance. No merge/deploy/readiness is claimed.
The next normal release must inspect its exact saved Terraform plan, apply without
replanning, run additive migration 0021 (existing NOT VALID historical role FK),
then health and current nine-choice role/session-create smoke. Those steps are
NOT TESTED by this build-only task; no live runtime or existing session was changed.

## RU — перевод проверенного результата и границ

Исходная база — `ceef39a89f00935f30a91141ace5b25ceeca68cd`, request #33.
Старый архив воспроизвёл ошибку consumer hashes до apply/миграций.
Сверены все consumers: изменён только hash Questions v2, исторический Role JSON
исключён из действующего списка. Версии, остальные hashes и runtime не изменены.

Создан новый отдельный private object: 35027 байт, generation
`1794851467699526`, SHA-256 `6f6d9b114efbdb923795f4f10776dc2a89b00e293d551a6e0c07a020e3395e6a`.
Обратное скачивание побайтно совпало. Шесть файлов исходного semantic store,
ACTIVE и validation report побайтно сохранены; изменено только поле
`consumer_artifacts` manifest. Состав 392/584/21, provenance и явные gaps сохранены.
Новый Knowledge release не квалифицировался и не активировался.

Обновлён только существующий preprod Environment pin; GET подтвердил точное значение.
Production, IAM, secrets, workflows, роль-каталог, БД и миграции не менялись.
Оригинальный архив и его generation сохранены. JSON выше — точный handoff pin.

Целевые transport/rebind тесты: 18 PASS / 4,13 с; дополнительный pin-test и
CI ownership проверки указаны отдельно в PR. Первый запуск остановлен из-за
ошибки тестового ZIP-helper, затем helper исправлен и временный файл удалён.
Полного API-прогона и Full Regression не было.

Реальная Docker-сборка через существующий Cloud Build: SUCCESS / 64,3 с.
API base и неизменённый overlay verifier прошли; испорченный manifest hash и
изменённые байты Questions ожидаемо отклонены. Ссылки, точные hashes и матрицы
выше общие для EN/RU; PASS сборки не означает независимую приёмку или deployment.

Далее координатор проверяет PR, выполняет merge и штатный exact-plan rollout,
проверяет миграцию 0021, HTTPS и создание сессии с текущими девятью ролями.
Эти live-шаги здесь NOT TESTED. Merge, deployment и изменение существующих
пользовательских сессий не выполнялись.
