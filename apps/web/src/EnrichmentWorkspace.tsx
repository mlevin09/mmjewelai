import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
  const navigate = useNavigate();
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
  const [partialAnswer, setPartialAnswer] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [completedFrame, setCompletedFrame] = useState<string | null>(null);
  const [pieceCreating, setPieceCreating] = useState(false);
  const [guidedType, setGuidedType] = useState("");
  const [guidedMetal, setGuidedMetal] = useState("");
  const [guidedStone, setGuidedStone] = useState("");
  const [guidedStyle, setGuidedStyle] = useState("");
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
    const outputReady =
      data.state?.status === "final_output_ready" ||
      data.state?.status === "final_output_ready_with_unresolved";
    setFinalReason(
      data.state
        ? outputReady
          ? "Loading server output…"
          : "final_output_blocked"
        : "",
    );
    if (data.state && outputReady) {
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

  async function perform(
    action: () => Promise<unknown>,
    clearText = false,
    onSaved?: () => void,
  ) {
    if (flight.current) return;
    flight.current = true;
    setBusy(true);
    setCompletedFrame(null);
    setError("");
    setCopyStatus("");
    setFinal(null);
    setFinalReason("Updating server output…");
    try {
      await action();
      if (clearText) setText("");
      await refresh();
      onSaved?.();
    } catch (e) {
      setFinal(null);
      setError(
        e instanceof ApiError && e.status === 409
          ? t(
              "The design changed or a decision still needs confirmation. Your input is kept here. Review the updated description before retrying.",
              "Дизайн изменился или решение ещё требует подтверждения. Ваш ввод сохранён на экране. Проверьте актуальное описание и повторите попытку.",
            )
          : e instanceof ApiError
            ? e.status === 401 || e.status === 403
              ? t(
                  "Your session needs attention. Sign in again or check your access.",
                  "Требуется повторный вход или проверка доступа.",
                )
              : t(
                  "The answer could not be saved. Your input remains available; retry after checking the connection.",
                  "Не удалось сохранить ответ. Введённый текст остаётся доступен; проверьте соединение и повторите попытку.",
                )
            : t(
                "Connection interrupted. Your latest input remains available; retry when the connection recovers.",
                "Соединение прервано. Введённый текст сохранён на экране; повторите попытку после восстановления связи.",
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
      let decisionCommitted = false;
      if (hasDecision) {
        await client.answer(
          state,
          question,
          decision as
            "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN",
          option,
        );
        decisionCommitted = true;
      }
      const written = [
        value.trim()
          ? `${question.question_kind === "NATIVE" ? question.native_question.text : question.offer.rendered_question}: ${value.trim()}`
          : "",
        note.trim(),
      ]
        .filter(Boolean)
        .join("\n");
      if (written) {
        // An answer may advance the server revision. Read the new head before
        // submitting any additional free text through the existing API.
        try {
          const fresh = hasDecision ? await client.read() : snapshot!;
          await client.send(session!, fresh, written);
          setPartialAnswer(null);
        } catch (e) {
          if (decisionCommitted) setPartialAnswer(written);
          throw e;
        }
      } else {
        setPartialAnswer(null);
      }
    });
  }

  async function newPiece() {
    if (flight.current || pieceCreating || !session) return;
    setPieceCreating(true);
    setError("");
    try {
      const created = await api.request<Session>(
        `/projects/${session.project_id}/sessions`,
        {
          organizationId,
          method: "POST",
          body: JSON.stringify({
            role_id: session.role_id,
            locale: session.locale,
          }),
        },
      );
      void navigate(
        `/organizations/${organizationId}/sessions/${created.session_id}`,
      );
    } catch {
      setError(
        t(
          "Could not create a new piece. This design has not been changed. Please retry.",
          "Не удалось создать новое изделие. Текущий дизайн не изменён. Повторите попытку.",
        ),
      );
    } finally {
      setPieceCreating(false);
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
        <Link to={`/organizations/${organizationId}`}>Back to projects</Link>
      </main>
    );
  const s = snapshot.state;
  const activeQuestion = s?.questions[0];
  const readyForFinal =
    s?.status === "final_output_ready" ||
    s?.status === "final_output_ready_with_unresolved";
  const unsavedDesignInput = [guidedType, guidedMetal, guidedStone, guidedStyle, text].some((value) => value.trim());
  const canComplete = Boolean(readyForFinal && !unsavedDesignInput);
  const finalConfirmed = Boolean(
    completedFrame === s?.current_frame.history_root_sha256 &&
    canComplete &&
    final,
  );
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
          <p className="eyebrow">
            {t("JEWELAI DESIGN STUDIO", "СТУДИЯ ДИЗАЙНА JEWELAI")}
          </p>
          <h1>{t("Design your piece", "Создайте своё украшение")}</h1>
          <p className="design-hero-subtitle">
            {t(
              "Describe the piece, choose its details and refine one current design brief.",
              "Опишите изделие, уточните параметры и получите одно актуальное описание.",
            )}
          </p>
        </div>
        <div className="piece-actions">
          <span className="studio-state">
            {s
              ? t("Piece in progress", "Изделие в работе")
              : t("New piece", "Новое изделие")}
          </span>
          <button
            type="button"
            className="new-piece-button"
            disabled={busy || pieceCreating}
            onClick={() => void newPiece()}
          >
            {pieceCreating
              ? t("Creating…", "Создаём…")
              : t("+ New Piece", "+ Новое изделие")}
          </button>
        </div>
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {partialAnswer && (
        <section
          className="alert"
          aria-label={t(
            "Partially saved clarification",
            "Частично сохранённое уточнение",
          )}
        >
          <strong>
            {t(
              "The selected option was saved, but additional text may not be fully applied.",
              "Выбранный вариант сохранён, но дополнительный текст мог примениться не полностью.",
            )}
          </strong>
          <p>
            {t(
              "Check the updated design and message history before resending these details; do not repeat the option selection.",
              "Проверьте обновлённый дизайн и историю перед повторной отправкой деталей; не выбирайте тот же вариант повторно.",
            )}
          </p>
          <textarea
            aria-label={t(
              "Additional text to review",
              "Дополнительный текст для проверки",
            )}
            readOnly
            value={partialAnswer}
          />
          <button
            className="quiet"
            type="button"
            onClick={() => setPartialAnswer(null)}
          >
            {t("I reviewed these details", "Я проверил эти детали")}
          </button>
        </section>
      )}
      <div className="enrichment-grid" aria-busy={busy}>
        <section className="panel conversation-panel">
          <div className="conversation-heading">
            <div>
              <p className="eyebrow">{t("YOUR DESIGN", "ВАШ ДИЗАЙН")}</p>
              <h2>{t("Your piece", "Ваше изделие")}</h2>
            </div>
            <span className="conversation-saved">
              {t("Saved automatically", "Сохраняется автоматически")}
            </span>
          </div>
          <form
            className="guided-piece-form"
            onSubmit={(e) => {
              e.preventDefault();
              const payload = [
                guidedType.trim() ? `Jewelry type: ${guidedType.trim()}` : "",
                guidedMetal.trim() ? `Metal: ${guidedMetal.trim()}` : "",
                guidedStone.trim() ? `Center stone: ${guidedStone.trim()}` : "",
                guidedStyle.trim()
                  ? `Style and finish: ${guidedStyle.trim()}`
                  : "",
                text.trim(),
              ]
                .filter(Boolean)
                .join("\n");
              if (!payload) return;
              void perform(
                () => client.send(session, snapshot, payload),
                false,
                () => {
                  setGuidedType("");
                  setGuidedMetal("");
                  setGuidedStone("");
                  setGuidedStyle("");
                  setText("");
                },
              );
            }}
          >
            <div className="guided-heading">
              <div>
                <p className="eyebrow">
                  {t("DESIGN DETAILS", "ПАРАМЕТРЫ ИЗДЕЛИЯ")}
                </p>
                <h3>
                  {t("Start with what you know", "Начните с того, что знаете")}
                </h3>
              </div>
              <span>{t("All fields optional", "Все поля необязательны")}</span>
            </div>
            <div className="guided-fields">
              <label>
                {t("Jewelry type", "Тип изделия")}
                <input
                  list="piece-type-suggestions"
                  value={guidedType}
                  disabled={busy}
                  onChange={(e) => setGuidedType(e.target.value)}
                  placeholder={t(
                    "e.g. wedding band",
                    "Например: обручальное кольцо",
                  )}
                />
                <datalist id="piece-type-suggestions">
                  <option value={t("Wedding band", "Обручальное кольцо")} />
                  <option value={t("Engagement ring", "Помолвочное кольцо")} />
                  <option value={t("Earrings", "Серьги")} />
                  <option value={t("Pendant", "Подвеска")} />
                  <option value={t("Bracelet", "Браслет")} />
                </datalist>
              </label>
              <label>
                {t("Metal", "Металл")}
                <input
                  list="metal-suggestions"
                  value={guidedMetal}
                  disabled={busy}
                  onChange={(e) => setGuidedMetal(e.target.value)}
                  placeholder={t("e.g. yellow gold", "Например: жёлтое золото")}
                />
                <datalist id="metal-suggestions">
                  <option value={t("Yellow gold", "Жёлтое золото")} />
                  <option value={t("White gold", "Белое золото")} />
                  <option value={t("Rose gold", "Розовое золото")} />
                  <option value={t("Platinum", "Платина")} />
                  <option value={t("Silver", "Серебро")} />
                </datalist>
              </label>
              <label>
                {t("Center stone", "Центральный камень")}
                <input
                  list="stone-suggestions"
                  value={guidedStone}
                  disabled={busy}
                  onChange={(e) => setGuidedStone(e.target.value)}
                  placeholder={t(
                    "e.g. no stone / oval diamond",
                    "Нет камня / овальный бриллиант",
                  )}
                />
                <datalist id="stone-suggestions">
                  <option
                    value={t("No center stone", "Без центрального камня")}
                  />
                  <option value={t("Round diamond", "Круглый бриллиант")} />
                  <option value={t("Oval diamond", "Овальный бриллиант")} />
                  <option
                    value={t(
                      "Emerald-cut diamond",
                      "Бриллиант изумрудной огранки",
                    )}
                  />
                  <option value={t("Ruby", "Рубин")} />
                  <option value={t("Sapphire", "Сапфир")} />
                </datalist>
              </label>
              <label>
                {t("Style and finish", "Стиль и отделка")}
                <input
                  list="style-suggestions"
                  value={guidedStyle}
                  disabled={busy}
                  onChange={(e) => setGuidedStyle(e.target.value)}
                  placeholder={t(
                    "e.g. minimal, polished",
                    "Минимализм, полировка",
                  )}
                />
                <datalist id="style-suggestions">
                  <option value={t("Minimalist", "Минимализм")} />
                  <option value={t("Classic", "Классика")} />
                  <option value={t("Vintage", "Винтаж")} />
                  <option value={t("Modern", "Современный")} />
                  <option value={t("Polished", "Полировка")} />
                  <option value={t("Matte finish", "Матовая отделка")} />
                </datalist>
              </label>
            </div>
            <label className="free-design-text">
              {t(
                "Describe your idea or changes in your own words",
                "Опишите идею или изменения своими словами",
              )}
              <textarea
                aria-label={t("Your message", "Ваше сообщение")}
                id="guided-design-description"
                disabled={busy}
                maxLength={2000}
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t(
                  "What should the finished piece look and feel like?",
                  "Как должно выглядеть изделие? Какие детали важны?",
                )}
              />
            </label>
            <button
              disabled={
                busy ||
                ![guidedType, guidedMetal, guidedStone, guidedStyle, text].some(
                  (v) => v.trim(),
                )
              }
              type="submit"
            >
              {busy
                ? t("Updating your design…", "Обновляем дизайн…")
                : t("Update design", "Обновить дизайн")}
            </button>
            <small>
              {t(
                "JewelAI interprets these details using the existing API. Saved values appear in the current design, not in a second copy.",
                "JewelAI обрабатывает данные через существующий API. Сохранённые значения появятся в актуальном описании.",
              )}
            </small>
          </form>
          <section
            className="living-design"
            aria-label={t(
              "Current design text",
              "Актуальное описание украшения",
            )}
          >
            <p className="eyebrow">
              {t("CURRENT VERSION", "АКТУАЛЬНАЯ ВЕРСИЯ")}
            </p>
            <h3>
              {t("Your design, updated", "Ваше украшение — актуальный текст")}
            </h3>
            <p className="living-design-text" aria-live="polite">
              {s?.description.text ||
                t(
                  "Start by describing your jewelry below. Your saved answers will be reflected here in one current description.",
                  "Опишите своё украшение ниже. Сохранённые ответы будут отражены здесь в одном актуальном описании.",
                )}
            </p>
          </section>
          <div className="history-controls">
            <button
              className="quiet"
              type="button"
              onClick={() => setShowHistory((value) => !value)}
            >
              {showHistory
                ? t("Hide history", "Скрыть историю")
                : t("Show history", "Показать историю")}{" "}
              ({snapshot.events.length})
            </button>
            <button
              className="quiet"
              type="button"
              onClick={() => setShowHistory(false)}
            >
              {t("Clear visible history", "Очистить экран от истории")}
            </button>
            <small>
              {t(
                "History stays saved to this piece. New Piece starts a separate design.",
                "История остаётся сохранённой в этом изделии. «Новое изделие» создаёт отдельный дизайн.",
              )}
            </small>
          </div>
          {showHistory && (
            <details className="conversation-history" open>
              <summary>
                {t(
                  "Saved messages and decisions",
                  "Сохранённые сообщения и решения",
                )}
              </summary>
              <ol
                ref={log}
                className="conversation-log"
                aria-label={t("Saved conversation", "Сохранённая беседа")}
              >
                {snapshot.events.map((e) => (
                  <li key={e.event_id} className={`conversation-${e.kind}`}>
                    <strong>
                      {e.kind === "user"
                        ? t("Your message", "Ваше сообщение")
                        : e.kind === "question"
                          ? t("Question", "Уточнение")
                          : t("Saved decision", "Сохранённое решение")}
                    </strong>
                    {e.text !== e.outcome && <p>{e.text}</p>}
                    {e.outcome && <span className="badge">{e.outcome}</span>}
                  </li>
                ))}
              </ol>
            </details>
          )}
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
                  void submitClarification(
                    s,
                    activeQuestion,
                    decision,
                    option,
                    value,
                    note,
                  )
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
                        void submitClarification(
                          s,
                          q,
                          decision,
                          option,
                          value,
                          note,
                        )
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
        </section>
        <aside
          className="panel design-result"
          aria-label={t("Current design", "Текущий дизайн")}
        >
          <p className="eyebrow">
            {t("YOUR CURRENT BRIEF", "АКТУАЛЬНОЕ ОПИСАНИЕ")}
          </p>
          <h2>
            {t(
              "Design details and final prompt",
              "Параметры и итоговый промпт",
            )}
          </h2>
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
          <details className="saved-parameters">
            <summary>
              {t("Saved parameters", "Сохранённые параметры")} ({known.length})
            </summary>
            <dl className="design-facts">
              {known.map((f) => (
                <div key={f.path}>
                  <dt>{label(f.path)}</dt>
                  <dd>
                    {display(f.value)}{" "}
                    <small>
                      {f.origin}{" "}
                      {f.confirmed ? " · confirmed" : " · unconfirmed"}{" "}
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
          {s && (s.questions.length === 0 || readyForFinal) && (
            <section
              className="finish-design"
              aria-label={t("Finish your prompt", "Завершение промпта")}
            >
              <h3>{t("Anything else to add?", "Хотите добавить что-нибудь ещё?")}</h3>
              <p>{t(
                "You can refine the design again, or finish with the details you know. Unspecified characteristics stay unspecified; no defaults are invented.",
                "Вы можете снова уточнить дизайн или завершить его с известными характеристиками. Неуказанные значения остаются неуказанными — без значений по умолчанию.",
              )}</p>
              <div className="finish-design-actions">
                <button
                  type="button"
                  className="quiet"
                  onClick={() => {
                    setCompletedFrame(null);
                    document.getElementById("guided-design-description")?.focus();
                  }}
                >
                  {t("Yes, add details", "Да, добавить детали")}
                </button>
                <button
                  type="button"
                  disabled={busy || unsavedDesignInput || finalConfirmed}
                  onClick={() => {
                    setCompletedFrame(s.current_frame.history_root_sha256);
                  }}
                >
                  {t("No, I'm finished", "Нет, больше нечего добавить")}
                </button>
              </div>
              {unsavedDesignInput && (
                <p className="question-help">
                  {t(
                    "Save your entered details before finishing.",
                    "Сначала сохраните введённые детали, затем завершите работу.",
                  )}
                </p>
              )}
              {completedFrame === s.current_frame.history_root_sha256 && !readyForFinal && (
                <p role="status" className="finish-blocked">
                  {t(
                    "You have no more details to add, but the server still reports an unresolved blocking decision. Answer, skip, or mark remaining questions unknown where permitted. JewelAI cannot issue its authoritative final prompt yet.",
                    "Вы больше не хотите ничего добавлять, но сервер сообщает о нерешённом обязательном вопросе. Ответьте, пропустите или отметьте «Не знаю», если это разрешено. Итоговый промпт пока нельзя выдать.",
                  )}
                </p>
              )}
              {finalConfirmed && (
                <p role="status" className="finish-complete">
                  {t(
                    "Prompt Enrichment complete for this design. The server-generated final prompt is below.",
                    "Улучшение описания завершено. Ниже итоговый промпт, сформированный сервером.",
                  )}
                </p>
              )}
            </section>
          )}
          <h3>{finalConfirmed
            ? t("Final prompt", "Итоговый промпт")
            : t("Prompt preparation", "Подготовка промпта")}</h3>
          {finalConfirmed && final ? (
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
              <button className="quiet" type="button" onClick={() => void copyPrompt()}>
                {t("Copy full prompt", "Копировать весь промпт")}
              </button>
              <span role="status">{copyStatus}</span>
            </>
          ) : (
            <p>{readyForFinal
              ? t(
                  "The design is ready. Confirm that you have no more additions to see the final prompt.",
                  "Дизайн готов. Подтвердите, что больше нечего добавить, чтобы увидеть итоговый промпт.",
                )
              : friendlyFinalStatus(finalReason, ru)}</p>
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

type GuidedClarificationKind = "shape" | "dimensions" | "general";

function guidedClarificationKind(q: Question): GuidedClarificationKind {
  if (q.question_kind !== "NATIVE") return "general";
  const wording = q.native_question.text.toLowerCase();
  if (
    /(?:length|width|depth|dimensions?|размер|длин|ширин|глубин)/i.test(
      wording,
    ) &&
    /(?:stone|камн)/i.test(wording)
  )
    return "dimensions";
  if (
    /(?:shape|форм|cut|огранк)/i.test(wording) &&
    /(?:stone|камн)/i.test(wording)
  )
    return "shape";
  return "general";
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
  const [lengthMm, setLengthMm] = useState("");
  const [widthMm, setWidthMm] = useState("");
  const [depthMm, setDepthMm] = useState("");
  const kind = guidedClarificationKind(q);
  const native = q.question_kind === "NATIVE" ? q.native_question : null;
  const allowed = native
    ? decisions(native)
    : q.question_kind === "KEEP_RELEASE"
      ? q.offer.allowed_decisions
      : [];
  const options =
    native && allowed.includes("SELECT_OPTION") ? native.options : [];
  const labels: Record<string, string> = {
    ACCEPT: ru ? "Принять" : "Accept",
    REJECT: ru ? "Отклонить" : "Reject",
    SKIP: ru ? "Пропустить" : "Skip",
    UNKNOWN: ru ? "Не знаю" : "I don't know",
  };
  const selectedOption = options.find(
    (o) => (o.option_id ?? o.value) === choice,
  );
  const selectedDecision = selectedOption ? "SELECT_OPTION" : choice;
  const dimensionText = [
    lengthMm.trim() ? `${ru ? "Длина" : "Length"}: ${lengthMm.trim()} mm` : "",
    widthMm.trim() ? `${ru ? "Ширина" : "Width"}: ${widthMm.trim()} mm` : "",
    depthMm.trim() ? `${ru ? "Глубина" : "Depth"}: ${depthMm.trim()} mm` : "",
  ]
    .filter(Boolean)
    .join("; ");
  const enteredValue = kind === "dimensions" ? dimensionText : value;
  const canSend = Boolean(
    (selectedDecision &&
      allowed.includes(
        selectedDecision as
          "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN",
      )) ||
    enteredValue.trim() ||
    note.trim(),
  );
  return (
    <section className="clarification-card">
      <h3>
        {q.question_kind === "KEEP_RELEASE"
          ? q.offer.rendered_question
          : q.native_question.text}
      </h3>
      <div className="clarification-inputs">
        <label>
          <span>{ru ? "Параметр / решение" : "Parameter / decision"}</span>
          <select
            value={choice}
            disabled={busy}
            onChange={(e) => setChoice(e.target.value)}
          >
            <option value="">
              {ru
                ? "Выберите вариант (необязательно)"
                : "Choose an option (optional)"}
            </option>
            {options.map((o) => (
              <option
                value={o.option_id ?? o.value}
                key={o.option_id ?? o.value}
              >
                {o.label}
              </option>
            ))}
            {allowed
              .filter((d) => d !== "SELECT_OPTION")
              .map((d) => (
                <option value={d} key={d}>
                  {labels[d]}
                </option>
              ))}
          </select>
        </label>
        {kind === "shape" ? (
          <label>
            <span>
              {ru ? "Форма центрального камня" : "Center stone shape"}
            </span>
            <input
              list="center-stone-shape-suggestions"
              value={value}
              disabled={busy}
              maxLength={500}
              aria-label={ru ? "Форма камня" : "Stone shape"}
              placeholder={
                ru
                  ? "Выберите форму или напишите свою"
                  : "Choose a shape or type your own"
              }
              onChange={(e) => setValue(e.target.value)}
            />
            <datalist id="center-stone-shape-suggestions">
              {[
                ["Round", "Круглая"],
                ["Oval", "Овальная"],
                ["Princess", "Принцесса"],
                ["Emerald", "Изумрудная"],
                ["Pear", "Грушевидная"],
                ["Cushion", "Кушон"],
                ["Marquise", "Маркиз"],
                ["Heart", "Сердце"],
              ].map(([en, russian]) => (
                <option key={en} value={ru ? russian : en} />
              ))}
            </datalist>
            <div
              className="stone-shape-choices"
              role="group"
              aria-label={
                ru ? "Подсказки формы камня" : "Suggested stone shapes"
              }
            >
              {[
                ["Round", "Круглая"],
                ["Oval", "Овальная"],
                ["Princess", "Принцесса"],
                ["Emerald", "Изумрудная"],
                ["Pear", "Грушевидная"],
                ["Cushion", "Кушон"],
                ["Marquise", "Маркиз"],
                ["Heart", "Сердце"],
              ].map(([en, russian]) => {
                const suggestion = ru ? (russian ?? en) : en;
                return (
                  <button
                    type="button"
                    key={en}
                    className={
                      value === suggestion
                        ? "shape-choice selected"
                        : "shape-choice"
                    }
                    aria-pressed={value === suggestion}
                    disabled={busy}
                    onClick={() => setValue(suggestion)}
                  >
                    {suggestion}
                  </button>
                );
              })}
            </div>
            <small className="question-help">
              {ru
                ? "Это подсказки ввода, не варианты, подтверждённые сервером. Ваш выбор обрабатывается как текст."
                : "These are typing suggestions, not server-authorized answer options. Your choice is submitted as text."}
            </small>
          </label>
        ) : kind === "dimensions" ? (
          <fieldset className="stone-dimensions">
            <legend>{ru ? "Размеры камня, мм" : "Stone dimensions, mm"}</legend>
            <div className="dimension-fields">
              {[
                {
                  key: "length",
                  label: ru ? "Длина" : "Length",
                  current: lengthMm,
                  update: setLengthMm,
                },
                {
                  key: "width",
                  label: ru ? "Ширина" : "Width",
                  current: widthMm,
                  update: setWidthMm,
                },
                {
                  key: "depth",
                  label: ru ? "Глубина" : "Depth",
                  current: depthMm,
                  update: setDepthMm,
                },
              ].map((field) => (
                <label key={field.key}>
                  <span>{field.label}</span>
                  <input
                    type="number"
                    min="0.1"
                    step="0.1"
                    inputMode="decimal"
                    value={field.current}
                    disabled={busy}
                    aria-label={field.label + " (mm)"}
                    placeholder={ru ? "Необязательно" : "Optional"}
                    onChange={(e) => field.update(e.target.value)}
                  />
                </label>
              ))}
            </div>
            <small className="question-help">
              {ru
                ? "Заполните только известные размеры. Остальные можно оставить пустыми."
                : "Enter only known measurements. Leave the others blank."}
            </small>
          </fieldset>
        ) : (
          <label>
            <span>
              {ru ? "Ваше значение параметра" : "Your parameter value"}
            </span>
            <input
              value={value}
              disabled={busy}
              maxLength={500}
              placeholder={
                ru
                  ? "Введите значение для вопроса выше"
                  : "Enter a value for the question above"
              }
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
        )}
        <label>
          <span>
            {ru
              ? "Дополнительные пожелания / свободный текст"
              : "Additional preferences / free text"}
          </span>
          <textarea
            value={note}
            disabled={busy}
            maxLength={1400}
            aria-label={
              ru
                ? "Свободный ответ на уточнение"
                : "Clarification free-text answer"
            }
            placeholder={
              ru
                ? "Добавьте детали, которые важны для вас…"
                : "Add any details that matter to you…"
            }
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={busy || !canSend}
          onClick={() => {
            submit(
              (selectedDecision || "") as
                "SELECT_OPTION" | "ACCEPT" | "REJECT" | "SKIP" | "UNKNOWN" | "",
              selectedOption,
              enteredValue,
              note,
            );
          }}
        >
          {ru ? "Сохранить ответ" : "Save answer"}
        </button>
        {(allowed.includes("UNKNOWN") || allowed.includes("SKIP")) && (
          <div className="unknown-clarification-actions">
            {allowed.includes("UNKNOWN") && (
              <button
                type="button"
                className="quiet"
                disabled={busy || Boolean(enteredValue.trim() || note.trim())}
                onClick={() => submit("UNKNOWN", undefined, "", "")}
              >
                {ru ? "Не знаю — оставить неуказанным" : "I don't know — leave unspecified"}
              </button>
            )}
            {allowed.includes("SKIP") && (
              <button
                type="button"
                className="quiet"
                disabled={busy || Boolean(enteredValue.trim() || note.trim())}
                onClick={() => submit("SKIP", undefined, "", "")}
              >
                {ru ? "Пропустить этот вопрос" : "Skip this question"}
              </button>
            )}
          </div>
        )}
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
