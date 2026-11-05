import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiClient, ApiError } from "./api";
import {
  decisions,
  EnrichmentClient,
  type Conversation,
  type FinalOutput,
  type Question,
} from "./enrichment";
import type { Session } from "./types";

export function EnrichmentWorkspace({
  api,
  organizationId,
  sessionId,
}: {
  api: ApiClient;
  organizationId: string;
  sessionId: string;
}) {
  const client = useMemo(
    () => new EnrichmentClient(api, organizationId, sessionId),
    [api, organizationId, sessionId],
  );
  const [session, setSession] = useState<Session | null>(null);
  const [snapshot, setSnapshot] = useState<Conversation | null>(null);
  const [final, setFinal] = useState<FinalOutput | null>(null);
  const [finalReason, setFinalReason] = useState("");
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");
  const flight = useRef(false);
  const epoch = useRef(0);
  const log = useRef<HTMLOListElement>(null);
  const ru = session?.locale === "ru";
  const t = (en: string, russian: string) => (ru ? russian : en);
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [snapshot?.events.length]);

  async function refresh(currentEpoch = epoch.current) {
    if (currentEpoch !== epoch.current) return;
    const data = await client.read();
    if (currentEpoch !== epoch.current) return;
    setSnapshot(data);
    setLoading(false);
    setFinal(null);
    setFinalReason(data.state ? "Loading server output…" : "");
    if (data.state) {
      try {
        const output = await client.final(data.state);
        if (currentEpoch === epoch.current) {
          setFinal(output);
          setFinalReason("");
        }
      } catch (e) {
        if (currentEpoch !== epoch.current) return;
        if (e instanceof ApiError && e.status !== 401 && e.status !== 403)
          setFinalReason(e.code);
        else throw e;
      }
    }
  }
  useEffect(() => {
    let disposed = false;
    const current = ++epoch.current;
    void api
      .request<Session>(`/sessions/${sessionId}`, { organizationId })
      .then(async (data) => {
        if (disposed) return;
        setSession(data);
        await refresh(current);
      })
      .catch(() => {
        if (!disposed) {
          setSnapshot(null);
          setError(
            "Unable to open this Prompt Enrichment session. Check access and runtime availability.",
          );
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
      epoch.current++;
    };
    // The wrapper remounts on a scoped route change; refresh reads this exact client.
  }, [client]);

  async function perform(action: () => Promise<unknown>, clearText = false) {
    if (flight.current) return;
    flight.current = true;
    setBusy(true);
    setError("");
    setCopyStatus("");
    setFinal(null);
    setFinalReason("Updating server output…");
    try {
      await action();
      if (clearText) setText("");
      await refresh();
    } catch (e) {
      setFinal(null);
      setError(
        e instanceof ApiError
          ? `${e.code}: ${e.message}${e.status === 409 ? t(" — State changed; review the refreshed design before trying again.", " — Состояние изменилось; проверьте обновлённый дизайн перед повтором.") : ""}`
          : t(
              "Request could not be completed. Review the conversation before retrying.",
              "Запрос не выполнен. Проверьте беседу перед повтором.",
            ),
      );
      try {
        await refresh();
      } catch {
        // Preserve the last good snapshot; a network error must not erase the conversation UI.
        setError(
          t(
            "Could not refresh. Your saved conversation remains available; try again.",
            "Не удалось обновить. Сохранённая беседа доступна — повторите попытку.",
          ),
        );
      }
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  async function submitClarification(
    state: NonNullable<Conversation["state"]>,
    question: Question,
    decision: "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN" | "",
    option: { value: string; label: string; option_id?: string } | undefined,
    value: string,
    note: string,
  ) {
    await perform(async () => {
      const hasDecision = Boolean(decision);
      if (hasDecision) {
        await client.answer(state, question, decision as "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN", option);
      }
      const written = [
        value.trim() ? `${question.question_kind === "NATIVE" ? question.native_question.text : question.offer.rendered_question}: ${value.trim()}` : "",
        note.trim(),
      ].filter(Boolean).join("\n");
      if (written) {
        // An answer may advance the server revision. Read the new head before
        // submitting any additional free text through the existing API.
        const fresh = hasDecision ? await client.read() : snapshot!;
        await client.send(session!, fresh, written);
      }
    });
  }

  async function copyPrompt() {
    if (!final || flight.current) return;
    try {
      await navigator.clipboard.writeText(
        final.internal_final_prompt.prompt_text,
      );
      setCopyStatus(t("Copied", "Скопировано"));
    } catch {
      setCopyStatus(
        t(
          "Copy unavailable — select the text above.",
          "Копирование недоступно — выделите текст выше.",
        ),
      );
    }
  }
  if (loading)
    return (
      <main className="page" aria-busy="true">
        Loading conversation…
      </main>
    );
  if (!session || !snapshot)
    return (
      <main className="page">
        <p role="alert">{error || "Conversation unavailable."}</p>
        {session && (
          <p>
            <Link
              to={`/organizations/${organizationId}/sessions/${sessionId}/visualization`}
            >
              Open existing visualization workspace
            </Link>
          </p>
        )}
        <Link to={`/organizations/${organizationId}`}>Back to projects</Link>
      </main>
    );
  const s = snapshot.state;
  const activeQuestion = s?.questions[0];
  const fields = designFields(snapshot.revision.design);
  const known = fields.filter((f) => f.availability === "value");
  const unresolved = fields.filter((f) => f.availability !== "value");
  const dormant =
    s?.retained_base === "F"
      ? (s.native_frontier?.frontier_core.cause_states.filter(
          (c) => c.offer_state === "DORMANT" && c.status === "OPEN",
        ) ?? [])
      : [];
  return (
    <main className="page enrichment-page">
      <nav>
        <Link
          to={`/organizations/${organizationId}/projects/${session.project_id}`}
        >
          {t("Sessions", "Сессии")}
        </Link>{" "}
        / {session.role_id.replaceAll("_", " ")} ·{" "}
        {session.locale.toUpperCase()}
      </nav>
      <div className="design-hero">
        <div>
          <p className="eyebrow">{t("JEWELAI STUDIO", "СТУДИЯ JEWELAI")}</p>
          <h1>{t("Create your jewelry", "Создайте своё украшение")}</h1>
          <p className="design-hero-subtitle">
            {t(
              "Describe your idea. Refine the details together.",
              "Опишите идею. Вместе уточним детали вашего украшения.",
            )}
          </p>
        </div>
        <span className="studio-state">
          {s
            ? t("Design in progress", "Работа над дизайном")
            : t("Ready to begin", "Можно начинать")}
        </span>
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      <div className="enrichment-grid" aria-busy={busy}>
        <section className="panel conversation-panel">
          <div className="conversation-heading">
            <div>
              <p className="eyebrow">{t("YOUR DESIGN", "ВАШ ДИЗАЙН")}</p>
              <h2>{t("Conversation", "Беседа")}</h2>
            </div>
            <span className="conversation-saved">
              {t("Saved automatically", "Сохраняется автоматически")}
            </span>
          </div>
          <section className="living-design" aria-label={t("Current design text", "Актуальное описание украшения")}>
            <p className="eyebrow">{t("CURRENT VERSION", "АКТУАЛЬНАЯ ВЕРСИЯ")}</p>
            <h3>{t("Your design, updated", "Ваше украшение — актуальный текст")}</h3>
            <p className="living-design-text" aria-live="polite">
              {s?.description.text || t(
                "Start by describing your jewelry below. Your saved answers will be reflected here in one current description.",
                "Опишите своё украшение ниже. Сохранённые ответы будут отражены здесь в одном актуальном описании.",
              )}
            </p>
          </section>
          <details className="conversation-history">
            <summary>{t("Message history", "История сообщений")} ({snapshot.events.length})</summary>
            <ol ref={log} className="conversation-log" aria-label={t("Saved conversation", "Сохранённая беседа")}>
              {snapshot.events.map((e) => (
                <li key={e.event_id} className={`conversation-${e.kind}`}>
                  <strong>{e.kind === "user" ? t("Your message", "Ваше сообщение") : e.kind === "question" ? t("Question", "Уточнение") : t("Saved decision", "Сохранённое решение")}</strong>
                  {e.text !== e.outcome && <p>{e.text}</p>}
                  {e.outcome && <span className="badge">{e.outcome}</span>}
                </li>
              ))}
            </ol>
          </details>
          {s && activeQuestion && (
            <section
              className="clarification-area"
              aria-label={t("Design questions", "Вопросы о дизайне")}
            >
              <div className="clarification-heading">
                <span className="eyebrow">
                  {t("HELP US REFINE YOUR DESIGN", "ДАВАЙТЕ УТОЧНИМ ДЕТАЛИ")}
                </span>
                <span className="question-count">
                  {s.questions.length} {t("open", "открыто")}
                </span>
              </div>
              <QuestionCard
                q={activeQuestion}
                busy={busy}
                ru={ru}
                submit={(decision, option, value, note) =>
                  void submitClarification(s, activeQuestion, decision, option, value, note)
                }
              />
              {s.questions.length > 1 && (
                <details className="more-questions">
                  <summary>
                    {t("Other questions", "Другие вопросы")} (
                    {s.questions.length - 1})
                  </summary>
                  {s.questions.slice(1).map((q) => (
                    <QuestionCard
                      key={
                        q.question_kind === "NATIVE"
                          ? q.native_question.clarification_id
                          : q.offer.offer_id
                      }
                      q={q}
                      busy={busy}
                      ru={ru}
                      submit={(decision, option, value, note) =>
                        void submitClarification(s, q, decision, option, value, note)
                      }
                    />
                  ))}
                </details>
              )}
            </section>
          )}
          {dormant.map((c) => (
            <button
              className="quiet"
              key={c.cause_id}
              disabled={busy}
              onClick={() => void perform(() => client.resume(s!, c.cause_id))}
            >
              {t("Reopen clarification", "Вернуться к уточнению")}:{" "}
              {c.availability_target_ref.concrete_target.replaceAll("_", " ")}
            </button>
          ))}
          {s?.protection_projection.pending_requests
            .filter((p) => p.status === "RECONFIRMATION_REQUIRED")
            .map((p) => (
              <button
                className="quiet"
                key={p.intent_id}
                disabled={busy}
                onClick={() =>
                  void perform(() => client.resume(s, p.intent_id, true))
                }
              >
                {t(
                  "Reopen protected change",
                  "Вернуться к защищённому изменению",
                )}
              </button>
            ))}
          {s?.continuation_enabled && !s.extension_profile && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() => void perform(() => client.admit(s))}
            >
              {t(
                "Continue with protected changes",
                "Продолжить с защитой изменений",
              )}
            </button>
          )}
          <form
            className="message-composer"
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim())
                void perform(() => client.send(session, snapshot, text), true);
            }}
          >
            <label>
              {t("Your message", "Ваше сообщение")}
              <textarea
                required
                disabled={busy}
                maxLength={2000}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t(
                  "Describe your idea, add a detail, or request a correction…",
                  "Опишите идею, добавьте деталь или попросите исправление…",
                )}
              />
            </label>
            <button disabled={busy || !text.trim()} type="submit">
              {busy
                ? t("Processing…", "Обработка…")
                : t("Send message", "Отправить сообщение")}
            </button>
          </form>
        </section>
        <aside
          className="panel design-result"
          aria-label={t("Current design", "Текущий дизайн")}
        >
          <p className="eyebrow">{t("DESIGN PREVIEW", "ОБЗОР ДИЗАЙНА")}</p>
          <h2>{t("Your design so far", "Ваш текущий дизайн")}</h2>
          <p role="status">
            {s
              ? label(s.status)
              : t(
                  "Waiting for your first message",
                  "Ожидается первое сообщение",
                )}
          </p>
          {!known.length && (
            <p>
              {t(
                "No accepted characteristics yet.",
                "Принятых характеристик пока нет.",
              )}
            </p>
          )}
          <details className="saved-parameters"><summary>{t("Saved parameters", "Сохранённые параметры")} ({known.length})</summary>
          <dl className="design-facts">
            {known.map((f) => (
              <div key={f.path}>
                <dt>{label(f.path)}</dt>
                <dd>
                  {display(f.value)}{" "}
                  <small>
                    {f.origin} {f.confirmed ? " · confirmed" : " · unconfirmed"}{" "}
                    {f.locked ? " · LOCK" : ""}
                  </small>
                </dd>
              </div>
            ))}
          </dl>
          </details>
          {s?.protection_projection.roots.length ||
          known.some((f) => f.locked || f.confirmed) ? (
            <div className="design-notice">
              {t(
                "Confirmed and protected choices are preserved as you continue.",
                "Подтверждённые и защищённые решения сохраняются при продолжении беседы.",
              )}
            </div>
          ) : null}
          <details>
            <summary>
              {t(
                "Unknown / unresolved / not specified",
                "Неизвестное / неразрешённое / не указанное",
              )}
            </summary>
            <ul>
              {unresolved.map((f) => (
                <li key={f.path}>
                  {label(f.path)}:{" "}
                  {f.availability === "missing"
                    ? t("Not specified", "Не указано")
                    : f.availability}
                </li>
              ))}
            </ul>
            {s?.native_frontier?.frontier_core.cause_states
              .filter((c) => c.status === "OPEN")
              .map((c) => (
                <p key={c.cause_id}>
                  {c.availability_target_ref.concrete_target}: {c.status} /{" "}
                  {c.offer_state}
                </p>
              ))}
          </details>
          <h3>{t("Generated prompt", "Сформированный промпт")}</h3>
          {final ? (
            <>
              <p className="final-readiness">
                {humanReadiness(final.internal_final_prompt.readiness, ru)}
              </p>
              <textarea
                aria-label="Internal Final Prompt"
                className="final-prompt"
                readOnly
                value={final.internal_final_prompt.prompt_text}
              />
              <button
                className="quiet"
                onClick={() => {
                  void copyPrompt();
                }}
              >
                {t("Copy full prompt", "Копировать весь промпт")}
              </button>
              <span role="status">{copyStatus}</span>
            </>
          ) : (
            <p>{friendlyFinalStatus(finalReason, ru)}</p>
          )}
          <details className="evidence-details">
            <summary>
              {t("Why these design details?", "Откуда взялись детали дизайна?")}
            </summary>
            <p>
              {t(
                "These values come from your conversation. Unconfirmed details can still be changed.",
                "Эти характеристики взяты из беседы. Неподтверждённые детали можно изменить.",
              )}
            </p>
            <ul>
              {known.map((f) => (
                <li key={f.path}>
                  <strong>{label(f.path)}</strong>: {display(f.value)} —
                  {f.confirmed
                    ? t(" confirmed", " подтверждено")
                    : t(" not confirmed", " не подтверждено")}
                  {f.locked ? t(" (protected)", " (защищено)") : ""}
                </li>
              ))}
              {s?.protection_projection.roots.map((r, i) => (
                <li key={i}>
                  <strong>
                    {t("Preserved request", "Сохранённое пожелание")}
                  </strong>
                  : {r.source_wording}
                </li>
              ))}
            </ul>
          </details>
        </aside>
      </div>
    </main>
  );
}

function QuestionCard({
  q,
  busy,
  ru,
  submit,
}: {
  q: Question;
  busy: boolean;
  ru: boolean;
  submit: (
    decision: "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN" | "",
    option: { value: string; label: string; option_id?: string } | undefined,
    value: string,
    note: string,
  ) => void;
}) {
  const [choice, setChoice] = useState("");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const native = q.question_kind === "NATIVE" ? q.native_question : null;
  const allowed = native
    ? decisions(native)
    : q.question_kind === "KEEP_RELEASE"
      ? q.offer.allowed_decisions
      : [];
  const options = native && allowed.includes("SELECT_OPTION") ? native.options : [];
  const labels: Record<string, string> = {
    ACCEPT: ru ? "Принять" : "Accept",
    REJECT: ru ? "Отклонить" : "Reject",
    SKIP: ru ? "Пропустить" : "Skip",
    UNKNOWN: ru ? "Не знаю" : "I don't know",
  };
  const selectedOption = options.find((o) => (o.option_id ?? o.value) === choice);
  const selectedDecision = selectedOption ? "SELECT_OPTION" : choice;
  const canSend = Boolean((selectedDecision && allowed.includes(selectedDecision as "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN")) || value.trim() || note.trim());
  return (
    <section className="clarification-card">
      <h3>{q.question_kind === "KEEP_RELEASE" ? q.offer.rendered_question : q.native_question.text}</h3>
      <div className="clarification-inputs">
        <label>
          <span>{ru ? "Параметр / решение" : "Parameter / decision"}</span>
          <select value={choice} disabled={busy} onChange={(e) => setChoice(e.target.value)}>
            <option value="">{ru ? "Выберите вариант (необязательно)" : "Choose an option (optional)"}</option>
            {options.map((o) => (
              <option value={o.option_id ?? o.value} key={o.option_id ?? o.value}>{o.label}</option>
            ))}
            {allowed.filter((d) => d !== "SELECT_OPTION").map((d) => (
              <option value={d} key={d}>{labels[d]}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{ru ? "Значение параметра своими словами" : "Parameter value in your words"}</span>
          <input
            value={value}
            disabled={busy}
            maxLength={500}
            placeholder={ru ? "Например: ширина кольца 3 мм" : "For example: band width 3 mm"}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <label>
          <span>{ru ? "Дополнительные пожелания / свободный текст" : "Additional preferences / free text"}</span>
          <textarea
            value={note}
            disabled={busy}
            maxLength={1400}
            aria-label={ru ? "Свободный ответ на уточнение" : "Clarification free-text answer"}
            placeholder={ru ? "Добавьте детали, которые важны для вас…" : "Add any details that matter to you…"}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <button type="button" disabled={busy || !canSend} onClick={() => {
          submit(
            (selectedDecision || "") as "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN" | "",
            selectedOption,
            value,
            note,
          );
        }}>
          {ru ? "Сохранить ответ" : "Save answer"}
        </button>
        <p className="question-help">
          {ru
            ? "Можно заполнить один или все поля. Значения сохраняются через JewelAI, затем актуальное описание обновляется с сервера."
            : "Use any or all of these fields. JewelAI saves your answer, then refreshes the current design from the server."}
        </p>
      </div>
    </section>
  );
}
interface Field {
  path: string;
  availability: string;
  value?: unknown;
  origin?: string;
  confirmed?: boolean;
  locked?: boolean;
}
function designFields(value: unknown, path = ""): Field[] {
  if (value === null) return [{ path, availability: "missing" }];
  if (typeof value !== "object") return [];
  const obj = value as Record<string, unknown>;
  if (typeof obj.availability === "string")
    return [
      {
        path,
        availability: obj.availability,
        value: obj.value,
        origin: typeof obj.origin === "string" ? obj.origin : "",
        confirmed: obj.confirmed === true,
        locked: obj.locked === true,
      },
    ];
  return Object.entries(obj).flatMap(([key, v]) =>
    designFields(v, path ? `${path}.${key}` : key),
  );
}
function label(path: string) {
  return path.replaceAll("_", " ").replaceAll(".", " / ");
}
function display(value: unknown): string {
  if (Array.isArray(value)) return value.map(display).join(", ");
  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;
    if (typeof obj.value === "number" && typeof obj.unit === "string")
      return `${obj.value} ${obj.unit}`;
    return Object.entries(obj)
      .map(([key, v]) => `${label(key)}: ${display(v)}`)
      .join("; ");
  }
  return typeof value === "string" || typeof value === "number"
    ? String(value).replaceAll("_", " ")
    : JSON.stringify(value);
}

function friendlyFinalStatus(reason: string, ru: boolean): string {
  if (!reason || reason === "final_output_blocked")
    return ru
      ? "Для итогового промпта нужны ещё некоторые решения. Ответьте на вопросы слева или продолжите описание."
      : "A few design details still need your input. Answer a question or continue describing your jewelry.";
  return ru
    ? "Не удалось загрузить итоговый результат. Ваша беседа сохранена, попробуйте обновить страницу."
    : "The final result could not be loaded. Your conversation is saved; try refreshing.";
}

function humanReadiness(readiness: string, ru: boolean): string {
  if (readiness === "READY" || readiness === "READY_WITH_UNRESOLVED")
    return ru
      ? "Промпт сформирован. Можно скопировать результат."
      : "Your prompt is available. Copy it when you're ready.";
  return ru ? "Продолжите уточнять дизайн" : "Continue refining your design";
}
