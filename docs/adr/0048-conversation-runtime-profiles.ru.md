# ADR 0048 — Конфигурация разговорных runtime и безопасные эксплуатационные данные

RU TRANSLATION · 2026-11-20 · Issue #191 · реализация для независимого review.
EN MASTER: [0048](0048-conversation-runtime-profiles.md). Активации, квалификации
профессионального качества, deployment и функциональной приёмки нет.

## Контекст и решение

[ADR 0047](0047-us01-dual-interpretation-commit-aware-reply.md) сохраняет силу:
модель и Parser независимо читают исходный текст; только SO/Matrix разрешает State;
после commit модель предлагает ответ, который проходит действующую проверку фактов.
HTTP 200 и наличие конфигурации не доказывают правильную интерпретацию или ответ.

Повторно используем `ConversationModel`, `QwenConversationConfig` и llama.cpp adapter.
Реестр на старте выбирает явно разрешённый профиль. Второго разговорного ядра,
Parser, State, контроллера экспериментов или provider service нет.

- `ST01_CONVERSATION_PROFILES_JSON`: массив до 16 конфигураций.
- `ST01_CONVERSATION_ACTIVE_PROFILE`: точный ID или `disabled`.
- Обязательны `profile_id`, `engine=llama_cpp`, boolean `approved`, точный private
  `endpoint`, `model`, `model_sha256`, `runtime_build`, `context_tokens`. Dataclass
  проверяет sampling, timeout, ограничения ответа, отсутствие streaming и одну
  попытку. Неизвестные поля, повторные ключи/ID и недопустимый выбор блокируют старт.
  `approved` — декларация оператора, а не удалённая аттестация модели.
- Анонимный named profile допускается только на loopback. Удалённый требует HTTPS
  и `bearer_env` (ссылка на secret env, не inline) либо `google_id_token` с точным
  HTTPS origin audience. Токены только на сервере, без redirects/retries. Это не
  создаёт сертификаты, gateway, VPC route, IAM grants или secrets.
- Старый `ST01_CONVERSATION_PROVIDER=qwen` поддерживается. Смешение с активным
  named profile запрещено. Явный `disabled` имеет приоритет.
- Preprod читает `infra/terraform/preprod/conversation.json` в эти две переменные.
  Он **выключен, реестр пуст**. После review переключение A→B→A требует только
  config deployment, не business-code changes. Production и generation profiles не меняются.

Используем существующие свободные `model_runtime`/`sampling`: profile, engine,
model/artifact/build, параметры inference и hash endpoint. Нет новых таблиц, DTO,
public routes или schema versions. Сохранённые ответы читаются с их provider/model,
не с текущим профилем. Pending turn при смене runtime получает существующий 409 до
нового reply call. Чтение и idempotent replay не вызывают модель. Проверки источника,
State и хешей сохраняются.

В числовых phase logs: Message ID, model/pins/configuration hash, результат недоверенного
proposal или bounded error и latency. Нет текста, headers, raw exceptions, provider
bodies или credentials. Draft не объявляется принятым State или проверенным ответом.

## Модель и инструкции

Фактические сохранённые ответы отклонены `checked_reply()`: RU не подтвердил принятые
критические факты; EN не прошёл проверку непринятого факта sapphire. Оба не уточнили
распределение количества. Интерпретации содержали неверные metal values/quotes, поэтому
SO правильно не принял металл. Ограниченная проверка усиленных инструкций
снова дала неверные spans и ложные saved claims, с худшей latency (RU 104.516s, EN 94.821s).
Этот эксперимент не сохраняется в final patch. Исходные инструкции, validator и SO
не изменены. Model-quality FAIL не исправляется конфигурацией или HTTP success и
остаётся явным blocker, с честным fallback и неизменённой историей.

Штатный boot lab загружает Qwen3-1.7B, context 2048, два threads, reasoning budget zero.
Отдельно наблюдавшийся Qwen3-4B работал с context 4096; исследовательская установка не
становится boot default или qualified profile автоматически. Модель и systemd здесь
не меняются. Операторский IAP/SSH не является API data plane.

## STT latency

Cloud Run evidence и четыре настоящих authenticated synthetic-audio запроса показывают:
первый запрос в основном ждёт cold startup, warm inference быстрее. Существующий public
proxy удаляет внутренний `processing_ms`. Добавлены private numeric `audio_read_ms`,
`auth_ms`, `upstream_ms`, проверенный `processing_ms`, total и outcome/request identity.
Audio read начинается после multipart parsing, это не browser recording/upload timing.
Неверный необязательный timing не меняет public ответ из трёх полей. Нет логирования
аудио, транскрипта, токенов или URL.

Startup probe preprod: period/timeout 1 секунда, threshold 240; прежний startup budget
240 секунд и проверка готовности модели сохраняются. Min0/max1, CPU/memory, image digest,
offline network и IAM не меняются. Убирается до девяти секунд *возможного ожидания probe*,
а не загрузка модели. Нет warm instance/CPU boost/GPU. [Документация probe](https://docs.cloud.google.com/run/docs/configuring/healthchecks).
Улучшение после deployment не заявляется без разрешённого deployment и измерения.

## Оставшийся существенный gate и альтернативы

API использует `jewelai-preprod-stt-caller`; VM — `default`, llama.cpp слушает localhost
без caller authentication. Один IP VM не создаёт безопасного inference route. Нельзя
открывать listener публично или выдавать API compute administration/SSH как обход.

До активации нужно одно infrastructure decision: одобрить reviewed private HTTPS
inference-only gateway на существующей VM, ограниченный route от API caller network,
TLS identity и доступ только API service identity. VM lifecycle/guest execution не
должны входить в API. Конкретный least-privilege plan и сертификат требуют review до
shared network/IAM/deployment changes. Код поддерживает caller auth, но инфраструктуру
не разворачивает.

Сохранить `disabled` до проверки qualified runtime и safe route. Deadline API 60 секунд
также обязателен; его увеличение само по себе не исправляет latency. Анонимный private
listener, public gateway, broad IAM, min1 STT и замена модели без qualification отклонены.
Full Regression — отдельный Owner gate; targeted exact-head CI не является независимой
функциональной приёмкой. Новых требований RU translation не вводит.
