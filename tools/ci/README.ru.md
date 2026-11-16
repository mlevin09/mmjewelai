# Risk-based PR checks (RU TRANSLATION)

CI-RISK-002 / ADR0045. EN MASTER — README.md. Активный pr_routes.json version2 расширяет
существующий selector, native pytest reporter и fail-closed runner. Required PR identity
`Runtime API` / job `runtime` сохраняется. Branch protection, product semantics и DB guard
не изменяются. Release decision: docs/adr/0045-risk-based-pr-and-release-qualification.md.

## Selection

- Точный PR HEAD сравнивается с реальным merge base по всем feature commits.
- Явный component ownership связывает изменённые Python declarations с direct/integration
  contracts. Изменение Roles не выбирает все Parser, Prompts, provider или API packages.
- Изменённая native test function включает все parametrized cases, без sampling.
- Текущие shared bootstrap/helper transitions зарегистрированы semantic source hashes
  before/after и явными contract tests. Будущее изменение нарушает пару и BLOCK до review
  dependency coverage. Сам факт импорта не доказывает coverage.
- Неизвестные executable declarations, helpers/fixtures/resources BLOCK с путём и причиной.
  V2 не переключается на v1. Явный полный resource ownership важнее расширения документа.
  Синтетические v1 fixture-policy regressions сохранены.
- Web/infra передаются независимым проверкам. Isolated STT выполняет полные native tests
  без Torch/CUDA/weights. CI-only выполняет CI tooling, без API/migration.
- Backend risk сопровождается именованными state/authority, tenant, CAS/rollback и migration
  invariants. PostgreSQL serial за неизменённым repository/job/URL/container/cluster/freshness
  gate. Название test database само по себе не разрешает destructive tests.

## Выполнение и достоверные результаты

Все native collections проверяются ДО test bodies. Более800 cases BLOCK с
`automatic_pr_risk_budget_exceeded`; cap не увеличен, oversized coverage не становится зелёным.
Неизвестный ownership блокируется до установки зависимостей/DDL. Whole-API selection
останавливается до collection для bounded risk review.

Execution должен точно совпадать с collection: все parameters и полный успешный
setup/call/teardown. Missing/duplicate/skipped/interrupted/incomplete cases и отсутствующие
artifacts блокируют; реальные test failures дают FAIL. Нет continue-on-error/retry loop.
Superseded automatic PR checks отменяются; authorized manual Full Regression не отменяется.

summary.md / Actions summary содержит source/merge-base/selector SHAs, components,
targets/reasons, реальные counts/duration, bounded failed-case references и release status.
Полные причины — в selection artifact. Historical estimate явно частичный: известные case
seconds и число неизмеренных cases; это не current wall time и не разрешение parallelism.
Raw exception bodies, prompts, credentials/private payloads не публикуются; parameter IDs
хешируются существующим reporter.

## PR evidence не равно release qualification

Полный успешный targeted run возвращает PASS с `release_qualification=NOT_QUALIFIED`, если
не предоставлен validated exact-SHA Full receipt. Critical risk reasons сохраняются.
Full остаётся manual, отдельно authorized, exact-SHA и complete; четыре isolated API jobs,
serial PostgreSQL stage и coverage aggregate не меняются. PR CI не запускает Full.
Required check identities/permissions сохраняются.

**Owner gate для release enforcement:** существующие deployment workflows не проверяют
receipt. release-gate.proposed.patch НЕ применён; qualification.py latest — read-only discovery.
После явного одобрения предложенная preprod вставка проверяет successful exact-SHA Full run
и attempt-bound complete receipt ДО GCP auth/image build, без изменения GitHub policy и
без auto-Full. До approval/wiring разделение НЕ одобрено для integration/activation;
зелёный PR не является qualified release. Точный gate — в ADR0045. Production workflow не менялся.

## Ограниченный реальный замер

reference-qualification.json фиксирует реальные ROLES-001 source/base. Отдельный workflow
запускается при изменении descriptor или его workflow. Он использует прежние native runner
и disposable PostgreSQL, без нового test platform/provider calls/product edits. Subject SHA
и candidate selector SHA указываются отдельно. Допускаются только CI tooling/workflow overlays;
отсутствие product changes проверяется. Это evidence selector на реальном Role code,
не required-status override PR178, не Full Regression и не release qualification.
Обычный CI-only Runtime остаётся отдельным.

## Focused validation

Команды — в EN MASTER. Не запускать полный Runtime API или full_units.py как selector smoke.
Manual Full требует отдельного разрешения. Source-pair registrations и ownership evidence
требуют независимого review; зелёные тесты не означают принятие полноты coverage.
