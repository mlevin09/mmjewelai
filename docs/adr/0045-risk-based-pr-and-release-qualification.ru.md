# ADR 0045 — PR-проверки по объявлениям и отдельное release evidence (RU TRANSLATION)

Статус: реализация предложена в PR #179; независимый review ожидается.
Дата: 2026-11-16. Задание: CI-RISK-002. EN MASTER — одноимённый английский документ.

## Контекст

Реальный diff ROLES-001 (PR #178, fe5ec8466d2d6ca63a1fcb69483043aa0bbc3869)
выбрал 4 011 native cases. API-группа достигла timeout 1 200 секунд, хотя релевантные
role/migration/HTTP cases прошли. Объединение prefix buckets, целые Domain/Parser/Prompts
packages и транзитивные импорты тестовых файлов не отражали изменённое поведение.
Отдельное требование Full после выполнения мешало завершённому targeted PR стать зелёным.

## Решение

Сохраняются pytest runner, учёт cases, guardrail 800 cases, PostgreSQL identity gate,
required Runtime API job и manual Full workflow. Routing v2 использует изменённые
Python declarations и явный component ownership. Изменённые тест-функции включают
все native parameters. Неизвестные shared declarations, resources и helpers блокируются
с указанием путей и имён, без fallback к широким prefix-догадкам.

Текущие shared bootstrap/test-support изменения имеют проверенные semantic source-hash
пары before/after и контрактное/integration coverage. Это регистрации CI coverage,
не product compatibility paths и не разрешение произвольных будущих fixture edits.
Следующее изменение нарушает пару и блокируется. Импорт сам по себе не доказывает
полноту ownership ресурса. Новые source families требуют доказанной регистрации.
Синтетические v1 fixture-policy тесты сохранены; активная конфигурация репозитория — v2.
Никакой v2 FAIL не переключается на v1 routing.

Полный успешный targeted PR run возвращает PASS с явным release NOT_QUALIFIED.
Только validated Full receipt и read-only GitHub metadata точного release SHA могут
квалифицировать release. Нет automatic Full dispatch, пропуска coverage, status override
или изменения branch protection.

## Owner gate: release enforcement

Существующий preprod deployment workflow не проверяет Full receipt. Перенос enforcement
в защищённый deployment path — существенное изменение правила.
`tools/ci/release-gate.proposed.patch` — проверенное, НЕ применённое минимальное предложение:
найти успешный exact-SHA Full run, скачать attempt-bound receipt, проверить coverage и
authorization metadata до GCP authentication или image build. Отсутствующее, неуспешное,
истёкшее или несовпадающее evidence должно блокировать release. Read-only discovery
`qualification.py latest` реализован и проверен.

**Owner должен одобрить вставку deployment-rule до интеграции/активации разделения.**
Patch не применён; preprod и production workflows здесь не изменены. Существующие
защиты deployment-request SHA/exact-plan сохранены. PR PASS не доказывает enforcement
этого release-условия.

## Альтернативы и последствия

Отклонены: увеличение timeout/cap, удаление падающих тестов, import-reader inference,
PR-number exceptions и automatic Full Regression. Для будущего shared fixture edit
source-pair coverage требует явного review; такая консервативная стоимость сопровождения
предпочтительнее незаметно потерянных consumers.

Отдельный reference qualification workflow использует тот же runner на точном ROLES
source с наложением только candidate CI tooling/workflows. Он указывает subject SHA
и selector SHA, не квалифицирует release и не заменяет required status PR #178.
Изменения descriptor запускают ограниченный замер; обычный CI-only Runtime не выполняет
API bodies. Product files/shared data не меняются; PostgreSQL выполняется serial через
независимый gate.
