# ROLES-001 migration repair — Issue #182

## EN MASTER: cause and observed partial release

Base: `f56a59136df790c0b63e575b8b6ff26ce3f6fb99`, remote `jewelai-v2` verified before work.
PR #183 is merged as `a7534f880c8a47df1cfd21049e916ccaf77a56ac`.
[Deployment 43926475287](https://github.com/mlevin09/mmjewelai/actions/runs/43926475287)
passed build, exact plan/binding and apply, then failed migration execution
`jewelai-preprod-migration-89l96` (2026-11-16 18:19:04 UTC).

Actual container traceback, not wrapper diagnosis:

```text
INFO Running upgrade 0020_session_retirement -> 0021_roles_foundation
File /app/packages/persistence/migrations/versions/0021_roles_foundation.py, line 50
FileNotFoundError: /app/packages/persistence/src/jewelai_persistence/role_seed.json
```

Connection/authentication and Alembic sequencing succeeded. The migration created
its transactional DDL, then failed while loading seed bytes, before the seed INSERT.
The shared Dockerfile installs persistence from a wheel and copies migrations/ini;
it intentionally does not install the repository's `packages/persistence/src` tree.
The original migration incorrectly resolved a source-checkout path from `__file__`.
The wheel already contains the correct resource: no Docker/packaging change is needed.

### Shared database — read-only observation

Existing authorized access, loopback Cloud SQL Auth Proxy, actual preprod database
credential used only in memory; no credential or row contents recorded. PostgreSQL
server option `default_transaction_read_only=on`, verified `transaction_read_only=on`,
5-second statement timeout; final rollback/close. Proxy stopped and listener removed.
No migration job execution, SQL writes, new database/user, IAM or shared configuration
change was performed by this task.

| Metadata queried after the failed execution | Actual result |
| --- | --- |
| Alembic revision | `0020_session_retirement` |
| `public.roles` | absent |
| `fk_design_session_current_role` | absent |
| Existing design-session count | 40 |

Together with transactional DDL and the exact exception, these observations confirm
0021 rolled back; no roles table/catalog or FK from that attempt persists. Forty is
an observed count, not a claimed comparison with an unavailable pre-failure snapshot.
No customer prompts, session payloads or generated assets were read.

### Cloud Run state is already partially updated

All three new revisions are Ready and receive 100% traffic. Ready is infrastructure
readiness, not proof that role-backed operations work against an unmigrated database.
The configured image digests below match the workflow's exact `f56a591...` registry
references; resolved runtime manifest digests are shown separately.

| Service / revision | Configured digest | Resolved runtime digest |
| --- | --- | --- |
| API `jewelai-preprod-api-00028-m5m` | `6662703b19c05189e55cf584ae69afb458a024c18ce564af1cb7472266e6752b` | `a1422bc39f659d7d52ef6cc33086e031d71f1896375b21965ef604234f9cfe33` |
| Web `jewelai-preprod-web-00032-m2f` | `4235b91fc7a141079547b3921578b23281c726e39320bdaab9e1991bc7927eda` | `7b12ed73c79be966ec5bf88afd03192f4fbdae1d302d25f8f1a0ceab47b2e3f1` |
| Worker `jewelai-preprod-generation-worker-00030-mkp` | `a35020efe448546cdc3a19836a09c721b1ffb84d04a5c1a032cac1ec364093c8` | `840424fabea8c1703710f53d302a65412e321e42d99b64c8da0dd2df789caeec` |

Identity Platform, HTTPS and nine-role live E2E were skipped by that failed workflow.
This task does not claim that those release gates passed.

## Minimal correction and invariant

Migration 0021 reads `role_seed.json` using standard-library
`importlib.resources.files("jewelai_persistence")`, with explicit UTF-8. It no longer
requires a source checkout. The existing bulk INSERT and single Alembic transaction
remain intact. Calling the explicit importer (which owns a separate transaction)
is intentionally unnecessary.

No schema, constraint, revision ID, seed data, import policy, canonical state,
application startup, UI, provider or Knowledge behavior changed. No new migration or
compatibility catalog was created. NOT VALID FK, RESTRICT deletion and guarded
downgrade remain unchanged. Completed 0021 migrations remain completed; ordinary
`upgrade head` does not reseed them.

Unchanged seed file: 1,012,871 bytes, SHA-256
`f39e3e9b241b4775ebbbfe27995a6b2edbdda16c5c8c41d81c0f59cf216934d0`.
Built persistence wheel contains these exact bytes. All 21 canonical identities,
nine passports, Studio selection and original role/source definitions are preserved.
The existing Knowledge object, selection JSON, consumer files and verifier are unchanged.

## Focused evidence and limits

- Baseline package-layout regression: FAIL with the same missing-source path, 1.00s.
- Corrected package-layout, URL round-trip and both downgrade guards: 4 PASS, 1.28s.
- Nearby catalog/session-selection and source/import controls: 2 PASS, 1.46s.
- Collection: ten cases in the Roles PostgreSQL module, 0.40s; collection is not PASS.
- Added PostgreSQL scenarios execute behind the **unchanged** existing
  `verified_ci_postgres()` repository/job/container/cluster/URL/freshness gate.
  No destructive local PG test is run because no qualifying local container exists.
  Actual execution receipts belong to the exact-head hosted CI reported in the PR.
- Positive PG scenario: copied container-layout migrations without `src`; upgrade
  from 0020 with a retained synthetic legacy session; 21 current roles; nine actual
  HTTP session choices; unchanged row snapshot; second `upgrade head` retains all
  role rows/timestamps; NOT VALID FK preserves the old row but rejects new invalid
  references (23503), and referenced-role deletion remains restricted.
- Negative PG scenarios: missing package resource and forced seed INSERT failure
  each roll back table/FK/version changes and retain the session; unmodified
  supported Alembic retry then creates all 21 roles. No test weakens shared guards.

[Actual image build/probe acc22e99-5d0c-4004-8bea-8c7ebac6d19e](https://console.cloud.google.com/cloud-build/builds;region=europe-west1/acc22e99-5d0c-4004-8bea-8c7ebac6d19e?project=483253159059):
SUCCESS, 67.2s (18:35:28–18:36:36 UTC). First it runs the actual deployed digest
and reproduces the path failure. Then it builds the unchanged API Dockerfile with
the corrected migration and verifies 21 canonical / nine passport records from the
installed site-packages resource with exact seed hash. Both probes use no-op SQL
operations and `--network=none`; they prove image packaging, not PostgreSQL DDL.
No image push, runtime deployment, or shared database connection occurs in this build.
Private build input: 296 files / 914,015 bytes, SHA-256
`04b0301e25721a71bc1ce260c2a5ae3b46fd74b16b1a82406375132fecf23a6e`.

Local Ruff/check/format and diff checks pass. No Full Regression, broad API run,
provider calls or production access. Remote Working Protocol Google Doc could not
be read: connected `get_document_text` returned an internal error. The explicit
Owner assignment, current AGENTS, repository development skill and ADR 0044 were
used; no missing policy or additional authority was invented.

## Coordinator continuation — after independent review

1. Review exact PR HEAD and native PG/CI receipts; merge only through the normal
   coordinator gate. Targeted CI does not substitute for separate release policy.
2. Recheck the actual shared revision and objects read-only. Expected current state
   is 0020, no roles/FK. If it differs, inspect it rather than stamp/reset/drop data.
3. Use the existing audited deployment-request flow with a new reviewed image that
   contains the correction. Inspect the exact saved Terraform plan for destructive
   or unrelated changes; apply that plan without replanning. Preserve the existing
   qualified Knowledge pin. Do not rerun the old broken image/job blindly.
4. Run the ordinary migration `alembic ... upgrade head` with that corrected image;
   then verify read-only: revision 0021, exactly 21 roles, unchanged retained records,
   NOT VALID FK and all nine configured Studio roles active.
5. Complete skipped Identity Platform and HTTPS readiness/health checks, then the
   authorized Studio nine-role catalog/session-create smoke. Preserve old sessions;
   retired six-role IDs are neither aliases nor an alternate runtime catalog.

Codex does not merge, stamp, manually import, deploy, recover shared data or self-accept.
No irreversible recovery or new Owner contract is required by the observed failure.

## RU — результат и граница продолжения

Ошибка миграции подтверждена traceback: seed читался по отсутствующему в Docker
пути исходников. Файл уже есть внутри wheel. Исправлены только две строки загрузки:
стандартный package resource и явная UTF-8; SQL, транзакция, seed и FK не менялись.

Read-only проверка preprod: revision 0020, таблицы roles и FK нет, наблюдается 40
сессий. Это подтверждает rollback миграции 0021. API/Web/worker уже переключены
Terraform на новые revisions с 100% трафика; их Ready не означает готовность Roles.
Точные configured/resolved digests приведены выше. Shared БД не изменялась.

Локально: RED воспроизведён, затем 4 PASS и 2 PASS; wheel содержит исходные seed
bytes. Реальная image-проверка SUCCESS / 67,2 с: старый опубликованный образ
воспроизводит ошибку, исправленный установленный пакет даёт все 21/9 записей.
Эти image-пробы не выполняют SQL. PostgreSQL-сценарии выполняются только штатным
CI за неизменённым disposable gate; их фактический результат указан в PR.

Координатор после review/merge продолжает обычный exact-plan rollout с исправленным
образом, проверяет revision 0021/21 ролей/сохранённые строки, затем IdP, HTTPS и
девять Studio-ролей. Не надо удалять сессии, stamp/reset БД, повторять broken job
или создавать старый role catalog. Knowledge pin сохранён. Codex не выполнял
merge, shared migration, deployment или доступ к production.
