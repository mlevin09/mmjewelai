# ADR 0047 — US-01: независимые интерпретации и ответ после commit

RU TRANSLATION английского master, 19.11.2026. Статус: реализация для независимого
review в Draft PR #185; не release, activation, deployment или acceptance.

## Контекст и полномочия

Architecture v0.5 и D3: установленная LLM интерпретирует исходный текст, Parser 1.3
независимо разбирает тот же текст. D2-A: проверенный scoped State commit и receipt
предшествуют естественному ответу. D5-B: неполная квалифицированная Library не
блокирует разработку; распознавание и рекомендация не означают согласие пользователя.

Ссылки и нормативная граница приведены в
[EN MASTER](0047-us01-dual-interpretation-commit-aware-reply.md).
Неутверждённые части proposed Boundary v1.1 не заменяют approved v1.0.
19 ноября Owner явно одобрил узкий additive versioned receipt и миграцию только
в коде PR. Старые receipt/0022, bytes/hashes/readers сохраняются. Однотранзакционный
ответ из ADR 0046 заменён только для нового schema2 пути; shared migration не разрешена.

## Решение

Повторно используются backend, authorization, DesignRevision, Parser, qualified
Library matcher, Matrix/Policy и revision-CAS. Новых сервиса, Parser, canonical store,
provider framework или профессионального каталога нет.

1. Schema2 сохраняет точный исходный текст, turn ID и expected revision. Dropdown
   хранится отдельно; editable transcript provenance — заявление клиента, не ASR proof.
2. `QwenConversationAdapter.interpret` получает исходный текст, scoped State,
   role/locale и typed selections; Parser candidates и готовых смысловых ответов нет.
   `SemanticProposal` — внутренний versioned untrusted DTO, не Parser evidence.
3. Текущий Parser независимо читает исходную строку. SO проверяет intent, spans,
   DIRECT mappings/Dictionary, component ownership, competing values и текущий State.
   Отсутствие Parser candidate не является автоматическим veto: может быть достаточен
   независимый exact source/mapping proof. Согласие интерпретаторов не даёт authority.
   Каждый proposal получает ACCEPT, CLARIFY или NO_COMMIT; Matrix может заблокировать
   source-eligible изменение до записи.
4. Записываются только три ранее одобренных initial bindings: тип изделия, материал
   корпуса и прилегающий цвет металла. Общая существующая проверка ownership не
   меняет исторический Parser. Сапфиры/count остаются evidence с unresolved attachment
   и quantity scope. Groups, EACH/PAIR/TOTAL, вес, происхождение и форма не угадываются.
5. Одна транзакция проверяет scoped session/artifacts/CAS/initial eligibility,
   записывает Message, необязательную следующую revision и immutable audit receipt.
   Полный read проверяется до commit; отказ не оставляет частичного source/State.
6. После commit SO читает фактическую revision. LLM получает сохранённые факты,
   accepted/unresolved outcomes и versioned grounding references; сама пишет
   естественный ответ, не выбирает template. Критическая проверка сверяет распознанные
   ювелирные факты, количества, компоненты, confirmation/protection и uncertainty.
   Успешный текст сохраняется без замены; invalid/unavailable output даёт явно
   помеченный fallback, не model success.
7. Write-once delivery — отдельная транзакция с input/revision/context hashes.
   PostgreSQL запрещает source mutation, повторную delivery и DELETE. Pending delivery
   отличается от committed State. Повтор turn не добавляет revision и не регенерирует
   сохранённый ответ. Явный идентичный POST может завершить только pending reply;
   GET не вызывает модель. При concurrent delivery возвращается сохранённый winner,
   а не несохранённый draft. GET/restart проверяют source/Matrix/revision/provenance без LLM.
   Downgrade с сохранёнными данными запрещён.

`initial_conversation_turn` — derived audit/delivery, не второй Product State.
Авторитетны существующие specification revisions. Старые F04 entrypoints отказывают
новому workflow; multi-turn continuation не реализуется молча.

## Runtime, безопасность и последствия

Существующие httpx и llama.cpp `/v1/chat/completions`: явные model/digest/build pins,
private literal-IP endpoint, без credentials в URL, redirects и auto retries,
с ограничениями bytes/tokens/time. Adapter не управляет VM, cloud credentials, shell
или State. Ошибки — bounded codes, без raw bodies/messages. Google conversational
adapter и Google-first fallback не подключены к schema2; legacy routes сохраняются.
Конфигурация opt-in/default off; cloud/production/workers/IAM/firewall/deployment
не меняются. Config pin не является remote attestation: actual model/private path
проверяются отдельно при release qualification.

Отвергнуты: переписывание receipt1/0022; assistant text в user Messages; прямые State
writes от LLM/Parser; сеть под DB locks; ложный success после post-commit failure;
whitelist/template selection вместо естественного ответа. Critical checker ограничен
текущими extractors и не доказывает истинность любой профессиональной прозы или
квалификацию неподкреплённых рекомендаций.

Mock и real-model evidence различаются. SQLite не квалифицирует PostgreSQL triggers;
DDL только за существующим disposable gate. Exact-head CI, model quality, UI
координатора, private connection, live auth и deployment — отдельные gates. Не
добавлены coverage/answer engine, Final Brief confirmation, IFP handoff, images,
research campaign или Full Regression. Перевод не вводит новых требований.

## Граница проверки по указанию Owner, 19 ноября 2026

Owner остановил дальнейшие Qwen-прогоны/настройку и направил работу на функциональную
интеграцию. VM TERMINATED; оставшиеся inference calls не расходуются. Mock HTTP/SQLite
проверяют orchestration, а не качество реальной модели, интерактивную задержку или
развёрнутое private connection. Существующий R1 operational reference не является
профессионально квалифицированным winning preset. PR не меняет конфигурацию сервера
или развёрнутый runtime.

Компактные quoted proposals сохраняют исходное evidence LLM. SO выводит span только
из единственного точного вхождения; repeated/missing quotes требуют clarification.
Ownership проверяется для каждого source occurrence, включая одинаковые значения.
Source-only mentions не разрешают ложные утверждения о сохранении unresolved фактов.
