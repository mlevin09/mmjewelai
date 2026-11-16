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
