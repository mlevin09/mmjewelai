# Проверка разработки ROLES-001 (RU TRANSLATION)

База: `262acb810f81cb75e6be0fa6d26361c7cdae0fdc`; ветка `codex/roles-001`.
Это доказательства разработки, не независимая приёмка, merge или deployment.

## Input → output

VERIFIED PASS на исходниках/SQLite: 15 обязательных исходных документов совпали по байтам
и SHA-256; 21 каноническая роль, девять полных 13-раздельных паспортов, 36 исходных persona,
12 ролей без выдуманных паспортов. Повторный импорт unchanged=21; изменение одного
определения обновляет одну строку/revision; следующий повтор unchanged=21. Повреждённый
source hash отклоняется до commit. Новое чтение сразу видит актуальное определение.

VERIFIED PASS HTTP: шесть старых ID, merged RR aliases и неразрешённый Studio ID отклонены.
Девять выборов упорядочены конфигурацией; внутренний каталог содержит 21 роль. Контекст
покупателя/CAD различается; passport остаётся DRAFT, policy отсутствует/null, прав роли нет.
EN-покупатель и RU-CAD проходят создание → ввод → вопрос о форме → oval → восстановление
в новом app/repository. Изумруд сохранён, овал принят, неизвестные размеры не выдуманы.
Stale CAS=409 без изменения revision; outsider запрещён; сохранённый design совпадает.
Повреждённое определение даёт безопасный 503 без synthetic sensitive marker и изменения
канонической ревизии. Принудительный запрет чтения role seed/legacy JSON не ломает startup
и чтение каталога. Domain сохраняет LOCK/confirmation/CAS для новых 21 ролей.

SKIP / NOT VERIFIED локально: настоящие PostgreSQL migration, ARRAY/JSONB и FK. Тест добавлен
за существующим неизменённым disposable-container/cluster/job gate; локального Docker нет.
Shared cleanup не выполнялся; NOT VALID FK сохраняет старые строки; downgrade блокирует
удаление используемых/изменённых ролей. UI, live deployment и активация профессиональной
Knowledge исключены: NOT TESTED / NOT PERFORMED; UI/release принадлежат координатору.

## Целевые receipts

- Пять domain-файлов roles/questions/rules/v2: **216 PASS**, 4.00s; после добавления timestamps
  schema equality отдельно PASS, 0.88s.
- `apps/api/tests/test_current_roles.py`: **7 PASS**, 7.47s на финальном catalog checkpoint.
- Ближайшие API role/session/catalog cases: девять случаев PASS в combined receipt
  (15 PASS, один PostgreSQL SKIP, 32 deselected; 18.18s до добавления no-fallback case).
- Persistence session/role: **2 PASS**, 33 deselected, 7.61s.
- Native Prompt Enrichment lifecycle + malformed catalog: **2 PASS**, 3.30s.
- Offline release verifier / mismatched consumer: **1 PASS**, 0.94s. Компиляция non-role
  artifacts допускает отсутствие registry; исполнение требует registry, без пустого fallback.
- Детерминированная пересборка seed побайтно совпадает, SHA-256
  `f39e3e9b241b4775ebbbfe27995a6b2edbdda16c5c8c41d81c0f59cf216934d0`.
- Ruff, format, компиляция изменённых Python, ссылки новых документов, diff-check: PASS.
- Alembic graph: один head `0021_roles_foundation`; это не выполнение PostgreSQL migration.

Повторы следовали изменениям: UUID/localized test fixtures, общий baseline/schema snapshots,
старые six-wording expectations, failure-safety и финальный catalog. Полный API/Full Regression
локально не запускались. Исходные ошибки не выдавались за PASS. Text-understanding provider
в соответствующих тестах mocked; платной LLM нет. Restart — новая HTTP app composition на
том же SQLite-файле, не preprod и не независимый перезапуск ОС-процесса.

## Источники и release

Архив `1L5eTL9wj1XyTwURkCFD6lVWMKsphToCY`, 238253 байта, SHA-256
`a2fc0f063a07fd51299bff9368139c077fea5998d65ba7b9c2c1e8a2e1fc69bb`.
Оригиналы в `data/roles/sources` побайтно сохранены; отдельный import manifest хранит их хеши.
DRAFT maturity не повышена. Legacy JSON runtime удалён, Git history сохранена. Старые
fixtures, role-specific wording и ожидания загрузки по role pin намеренно заменены;
current-session integrity, dictionary/provenance/authorization assertions сохранены.
Исторические пользовательские записи не переписывались и не удалялись.

Hosted exact-head CI и PostgreSQL execution — отдельный gate Draft PR. SQLite и code inspection
не выдаются за PostgreSQL qualification. Точные команды пяти domain-файлов находятся в EN MASTER.

Оригиналы находятся внутри побайтно сохранённого `data/roles/sources/original-role-sources.zip`;
import manifest идентифицирует отдельные файлы архива. Исходные Markdown hard-break пробелы
сохранены без отключения Git whitespace checks и без изменения исходных байтов.

## Исправление CI routing после первой публикации

На `0154dd5e797b3845e914397f7cf9fdc4121f46a6` Domain/Web/Infrastructure прошли.
Runtime API #43864842724 остановлен до тестов: `unmapped_impact_requires_routing_review`,
selected cases=0. PostgreSQL этим прогоном не квалифицирован.

Исправление декларирует полный Domain ownership изменённых schemas/catalog/source ресурсов,
добавляет реальный archive-hash/deterministic-seed тест и маршрутизирует release verifier,
новые fixture/builder paths. Shared helper/seed/source изменения явно сохраняют Full gate.
Алгоритмы/workflows/required checks/database safety gates не меняются. Локальный preflight:
blocked=[], full_required=true, 72 API targets. Existing selector: 42 PASS (34.23s);
новая проверка archive/builder PASS (3.46s). Full Regression не запускался. Hosted CI должен
подтвердить новый точный HEAD; старый source commit не выдаётся за новый PASS.

## Исправление import path native wrapper

На `530eaa1269c7a8d0fa0c59cfeeae0cddfe80640d` прошли проверка disposable PostgreSQL,
фактическая миграция и Alembic safety checks. Затем collection, не тесты, остановился:
entrypoint native script не включал корень checkout, `tests.current_roles` не импортировался.
Локальный bounded RED: ModuleNotFoundError, wrapper exitcode=2, collected=0 для
`test_parsed_enrichment.py`. API/domain conftest добавляет только фиксированный корень checkout
в test import path; production/алгоритмы CI не меняются. GREEN того же wrapper: 72 API cases
collected (27.27s), 76 test_roles cases collected (4.06s). Это COLLECTION receipts, не PASS выполнения.

Выполнение неизменённого native wrapper: EN/RU HTTP lifecycle + no-role-file-fallback:
**3 PASS**, exitcode=0, 32.49s. Выполнялись только три кейса, не полный API.


## Выполнение выбранных CI-тестов и исправление migration fixtures

Точный HEAD `5229cd35f9f7a423bd12fc9deb87ff39a5cc4c9b`: Domain, Web и
Infrastructure прошли. Runtime API #43868459903 **FAIL**: 661 PASS, 9 FAIL,
1 прерванный случай, 1 385 незавершённых/невыполненных из 2 055 выбранных API cases;
достигнут существующий лимит 1 200 секунд. Остальные выбранные suites только собраны,
не выполнены. Full qualification остаётся обязательной и не запускалась.

Артефакт `14228695746` (1 197 433 байта), SHA-256
`9df8934174e37ed77c26e3080f136c2dcd2bfb4ccfe47813a68ac0792a2610ef`:

- Новый PostgreSQL-тест Roles: ValueError до миграции, поскольку `%3D` отвергается
  интерполяцией Alembic ConfigParser. Локальный RED/GREEN подтверждает, что буквальный
  `=` корректно проходит ConfigParser и разбор URL SQLAlchemy.
- Восемь F04 PostgreSQL cases упали в общей migration fixture. Она ожидала старый отказ
  completion downgrade; теперь раньше срабатывает Roles retention, поскольку сохранённая
  сессия ссылается на RR-C25. Assertions требуют точный новый guard и сохраняют сравнение
  данных/схемы. Отдельные проверки старых completion/tombstone guards вызывают именно
  свои исторические guards, не позволяя новому отказу скрыть прежние защиты.
  Замороженный код миграций не изменён.
- Добавлены отрицательные unit-проверки Roles retention и повторное использование EN/RU
  HTTP lifecycle на независимо верифицированной PostgreSQL fixture. Локальные SQL cases
  остаются SKIP; квалификация БД требует фактического hosted выполнения.

Production-код, алгоритмы CI, timeout, PostgreSQL identity gate и требования покрытия
этим исправлением не изменены. Исходный CI FAIL сохранён и не объявлен PASS.
