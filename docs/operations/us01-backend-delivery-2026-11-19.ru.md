# US-01 backend — Owner Input → Output, 19 ноября 2026

RU TRANSLATION [EN MASTER](us01-backend-delivery-2026-11-19.md).
Тот же Draft [PR #185](https://github.com/mlevin09/mmjewelai/pull/185), ветка
`codex/st01-first-natural-turn`. Опубликованный parent
`cc92685bfdeb58f718e02f1f5112f8339202136c`; integration baseline
`ba422f81430a35d1dbaf6f781ee07e81b494a6f7`. Developer evidence не является
независимой функциональной приёмкой.

## Вход Owner и реализованный результат

Утверждённый D3: Qwen интерпретирует исходный человеческий текст; Parser 1.3
независимо читает те же bytes; SO сверяет интерпретации с source, ownership,
Dictionary/qualified Library, Matrix/Policy и текущим State. Ни один интерпретатор
не пишет State. D2-A: атомарно сохранить проверенные Message/State/input receipt,
прочитать committed revision, запросить и проверить естественный ответ, сохранить
write-once reply. Owner отдельно одобрил additive receipt2/migration0023 только
в коде. Последнее указание приостанавливает Qwen-прогоны/настройку и приоритизирует
функциональную интеграцию; оно не превращает неудачные live-сценарии в PASS.

**KEEP:** canonical revisions, spans/Message IDs, historical Parser readers, CAS,
tenant checks, qualified release pins, Matrix, raw bytes, предыдущий schema1.
**REWORK:** schema2 arbitration, commit-before-response, опциональная явная runtime
composition и контекстная проверка ответа.
**REMOVE из текущего uncommitted scope:** прежние Google-first adapter и UI changes;
они сохранены вне Git до восстановления. Studio интегрирует ChatGPT. Опубликованная
история не reset/rewrite.

Только тип изделия, материал корпуса и прилегающий цвет металла имеют существующие
утверждённые writable first-creation bindings. Сапфиры/count остаются source-backed
unresolved evidence; allocation, group, origin, weight и shape не выдумываются.
Это initial turn, а не multi-turn clarification, Final Brief или generation handoff.

## Backend/UI handoff

Существующий POST `/v1/sessions/{session_id}/prompt-enrichment/first-turn` принимает
`schema_version: "2.0.0"`, `turn_id`, `expected_revision_id`, точный `original_text`,
необязательный один qualified product в `selections` и user-reported transcript.
Предварительный Message POST для schema2 не нужен. Options читаются через scoped
`.../first-turn/options`. GET с `turn_version=2.0.0` возвращает committed evidence,
точный reply, текущие revision/brief и historical/current flag.

201=new/delivered; 200=identical replay; 202=input сохранён, delivery pending.
UI должен честно показывать origin model/fallback. Идентичный POST завершает только
pending reply, не повторяя interpretation и State append. GET/restart модель не
вызывают. Иные input/identity и stale revision конфликтуют; unauthorized access
скрывается. Непроверенный локальный draft не является read-back source. Schema1
не меняется.

## Фактическое функциональное evidence

- RU/EN HTTP text/dropdown/mixed/transcript используют реальные API, SO, Matrix,
  SQLAlchemy и disk SQLite с injected model. Три supported факта сохраняются;
  сапфиры/count не приобретают guessed placement. Новое приложение восстанавливает
  точный reply/evidence без model call. Это mocked-model tests.
- Отсутствие Parser candidate не является автоматическим veto при независимом
  exact qualified source proof. Вопросы, отрицания, рекомендации, непроверенное
  ownership и competing values не получают consent.
- Source/precommit rejection не меняет Message/revision/receipt. Failed reply после
  корректного commit сохраняет State и выдаёт честный fallback. Идентичный POST
  восстанавливает lost delivery без повторной interpretation/Message/revision.
  Write-once delivery возвращает сохранённого winner.
- Rehashed source/decisions/reply tampering отклоняется. Проверены tenant, stale CAS,
  существующее locked value и прежний schema1 reader.
- Новый RED: одинаковый gold у изделия и камня получал ownership первого occurrence;
  ответ мог объявить mentioned unresolved сапфиры сохранёнными. Два сбоя воспроизведены.
  GREEN: ownership проверяется по каждому source occurrence, false saved claims
  отклоняются, а правдивый not saved остаётся допустимой естественной формулировкой.
  Parser algorithm и historical evidence не изменены.

## Локальный журнал — checkpoints пересекаются, их нельзя суммировать как unique coverage

| Receipt / назначение | Результат | Секунды |
| --- | --- | ---: |
| qwen-transport, исходный offline adapter | 20 PASS | 5.93 |
| input modes checkpoint | 4 PASS / 1 FAIL | 21.95 |
| исправленные mixed/transcript | 4 PASS | 17.56 |
| guards checkpoint | 17 PASS / 1 FAIL | 72.04 |
| semantic source final checkpoint | 14 PASS | 7.91 |
| объединённые релевантные модули, один раз | 144 PASS / 9 deselected | 280.19 |
| compact quote/transport | 5 PASS | 2.15 |
| compact wire через HTTP/State, MockTransport | 2 PASS | 23.79 |
| pending delivery recovery | 2 PASS | 9.42 |
| последний ownership/reply RED | 2 FAIL / 2 PASS | 14.09 |
| последний affected GREEN | 18 PASS / 36 deselected | 70.00 |
| CI exact-source ownership checkpoint | 1 PASS | 0.18 |

Ранние ошибки сохранены: некорректный fake с bracketed prose; отсутствие проверки
owned counterpart; неверное ожидание теста об independent type; ошибки source
helper/import; mixed literal ownership; dropdown validation после model call.
Перед повтором выполнялось связанное исправление. Scratch evidence lookup ошибся
из-за смены pytest-current path; это failed read, не product acceptance.
Полный локальный API и Full Regression не запускались.

Точная команда последних affected cases приведена в EN MASTER. Combined144
предшествует compact transport/pending recovery/финальным source fixes; поздние
целевые проверки покрывают эти изменения. Exact-head hosted CI публикуется в PR,
а не выводится из старых зелёных runs. Три PostgreSQL cases собраны за неизменённым
disposable-target gate, локально **NOT TESTED**, не PASS. SQLite не квалифицирует
triggers/migration/downgrade.

## Реальная модель — не приёмка финального кода

Проверены фактические VM/model/runtime и `/health`, без новой установки, IAM или
firewall. Qwen3-1.7B-Q4_K_M.gguf SHA256
`d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5`;
llama.cpp b12110/cd959bae99ff4bed22bef2604f45241c09bbb8c8, context2048.
Шесть bounded synthetic calls за два CPU boot (~19 минут суммарно); VM в начале и
конце TERMINATED. Временные credential files и собственные probe payloads удалены;
исторические research results сохранены.

Tiny JSON generation200/~9s; full RU semantics timeout; RU reply200/~100s без
необходимого accepted canonical result. EN semantics200/~117s не прошла typed
semantic validation; EN reply200/~90s не доказал полный natural turn. Ошибка модели
не записала guessed State. Это **FAIL/incomplete** conversation scenarios, не
latency acceptance. Использовался более ранний adapter; последующие compact wire/
reference settings **NOT LIVE VERIFIED**.

[Предыдущий R1 report](https://drive.google.com/file/d/15qReuuUB9XBZNW6HPBseRq_k5DveBF_e/view)
выделил neutral B512 operational comparator, а не qualified professional winner
или product deployment. Первоначальные adapter defaults не полностью ему
соответствовали; расхождение сообщено. Явные reference settings добавлены локально
до остановки Qwen-работ Owner; deployed configuration не менялась. Дополнительные
неиспользованные calls не выполняются. Diagnostic ceiling240s — не обещание
Studio response time и не приемлемый измеренный пользовательский опыт.

## Открытые gates

| Gate | Статус |
| --- | --- |
| Source→dual interpretation→SO→Matrix→commit→reply с injected model | Developer-verified focused PASS |
| PostgreSQL qualification | Локально NOT TESTED; нужен exact-head hosted gate |
| Real final-code RU/EN interpretation/reply/latency | NOT VERIFIED; Qwen отложен Owner |
| Studio schema2/live identity/reload | Ответственность координатора, здесь NOT VERIFIED |
| Shared migration/runtime activation/deployment | NOT PERFORMED |
| Independent acceptance | Ожидает review координатора |

Не изменены cloud/production configuration, UI, Parser algorithm, professional
Knowledge, workers/image providers или CI enforcement. Добавлены только точные
CI ownership entries для нового кода/dependency; workflows/selector algorithms
сохранены. Нет merge, deployment, Full Regression или Knowledge activation.
