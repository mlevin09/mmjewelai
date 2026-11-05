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
          setFinalReason(`${e.code}: ${e.message}`);
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
        setSnapshot(null);
      }
    } finally {
      flight.current = false;
      setBusy(false);
    }
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
      <h1>{t("Design conversation", "Беседа о дизайне")}</h1>
      <Link
        className="legacy-link"
        to={`/organizations/${organizationId}/sessions/${sessionId}/visualization`}
      >
        {t(
          "Open existing visualization workspace",
          "Открыть существующий экран визуализации",
        )}
      </Link>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      <div className="enrichment-grid" aria-busy={busy}>
        <section className="panel conversation-panel">
          <h2>{t("Conversation", "Беседа")}</h2>
          <p>
            {t(
              "Messages are saved. Only server-accepted changes become design facts.",
              "Сообщения сохраняются. Только принятые сервером изменения становятся фактами дизайна.",
            )}
          </p>
          <ol
            ref={log}
            className="conversation-log"
            aria-label={t("Saved conversation", "Сохранённая беседа")}
          >
            {snapshot.events.map((e) => (
              <li key={e.event_id} className={`conversation-${e.kind}`}>
                <strong>
                  {e.kind === "user"
                    ? t(
                        "User · stored message",
                        "Пользователь · сохранённое сообщение",
                      )
                    : e.kind === "question"
                      ? t("JewelAI · clarification", "JewelAI · уточнение")
                      : t("Server decision", "Решение сервера")}
                </strong>
                {e.text !== e.outcome && <p>{e.text}</p>}
                {e.outcome && <span className="badge">{e.outcome}</span>}
              </li>
            ))}
          </ol>
          {!snapshot.events.length && (
            <p>
              {t(
                "Describe the jewelry you have in mind.",
                "Опишите украшение, которое хотите создать.",
              )}
            </p>
          )}
          {s?.questions.map((q) => (
            <QuestionCard
              key={
                q.question_kind === "NATIVE"
                  ? q.native_question.clarification_id
                  : q.offer.offer_id
              }
              q={q}
              busy={busy}
              ru={ru}
              answer={(decision, option) =>
                void perform(() => client.answer(s, q, decision, option))
              }
            />
          ))}
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
          <h2>{t("Current Product State", "Текущее состояние дизайна")}</h2>
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
          <h3>{t("Preservation and authority", "Сохранение и авторитет")}</h3>
          <p>
            KEEP: {s?.protection_projection.roots.length ?? 0} · LOCK:{" "}
            {known.filter((f) => f.locked).length} ·{" "}
            {t("Confirmed", "Подтверждено")}:{" "}
            {known.filter((f) => f.confirmed).length}
          </p>
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
          <h3>{t("Readable Description", "Описание украшения")}</h3>
          <p className="description-text">
            {s?.description.text ??
              t(
                "Available after your first message.",
                "Появится после первого сообщения.",
              )}
          </p>
          <h3>{t("Internal Final Prompt", "Внутренний финальный промпт")}</h3>
          {final ? (
            <>
              <p>{final.internal_final_prompt.readiness}</p>
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
            <p>
              {finalReason ||
                t(
                  "Not available yet. Continue the conversation or answer an offered clarification.",
                  "Пока недоступен. Продолжите беседу или ответьте на уточнение.",
                )}
            </p>
          )}
          <details>
            <summary>
              {t(
                "Advanced details: sources and evidence",
                "Подробности: источники и основания",
              )}
            </summary>
            <pre>
              {JSON.stringify(
                { revision: snapshot.revision, state: s, final },
                null,
                2,
              )}
            </pre>
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
  answer,
}: {
  q: Question;
  busy: boolean;
  ru: boolean;
  answer: (
    d: "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN",
    o?: { value: string; label: string; option_id?: string },
  ) => void;
}) {
  const native = q.question_kind === "NATIVE" ? q.native_question : null;
  const allowed = native
    ? decisions(native)
    : q.question_kind === "KEEP_RELEASE"
      ? q.offer.allowed_decisions
      : [];
  const labels = {
    ACCEPT: ru ? "Принять предложение" : "Accept offered change",
    REJECT: ru ? "Отклонить" : "Reject",
    SKIP: ru ? "Пропустить" : "Skip",
    UNKNOWN: ru ? "Не знаю" : "I don't know",
    SELECT_OPTION: "",
  };
  return (
    <section className="clarification-card">
      <h3>
        {q.question_kind === "KEEP_RELEASE"
          ? q.offer.rendered_question
          : q.native_question.text}
      </h3>
      {native && !native.options.length && (
        <p>
          {ru
            ? "Можно ответить сообщением ниже."
            : "You can reply in the message field below."}
        </p>
      )}
      {allowed.includes("SELECT_OPTION") &&
        native?.options.map((o) => (
          <button
            key={o.option_id ?? o.value}
            disabled={busy}
            onClick={() => answer("SELECT_OPTION", o)}
          >
            {o.label}
          </button>
        ))}
      {allowed
        .filter((d) => d !== "SELECT_OPTION")
        .map((d) => (
          <button
            className="quiet"
            key={d}
            disabled={busy}
            onClick={() => answer(d)}
          >
            {labels[d]}
          </button>
        ))}
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
