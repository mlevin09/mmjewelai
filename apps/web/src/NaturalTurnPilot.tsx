import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "./api";
import { VoiceRecorder } from "./VoiceRecorder";
import type {
  Conversation,
  EnrichmentClient,
  NaturalTurnOptions,
  NaturalTurnRead,
} from "./enrichment";
import type { Session } from "./types";

/** US-01 schema2: only server-confirmed State and reply may appear as saved. */
export function NaturalTurnPilot({
  client,
  session,
  snapshot,
  saved,
  options,
  onClose,
  onViewCurrent,
}: {
  client: EnrichmentClient;
  session: Session;
  snapshot: Conversation;
  saved: NaturalTurnRead | null;
  options: NaturalTurnOptions;
  onClose: () => void;
  onViewCurrent: () => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [selection, setSelection] = useState("");
  const [receipt, setReceipt] = useState<NaturalTurnRead | null>(saved);
  const [busy, setBusy] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState("");
  const turnId = useRef<string | null>(null);
  const flight = useRef(false);
  const ru = session.locale === "ru";
  const t = (en: string, russian: string) => (ru ? russian : en);

  async function run(action: "submit" | "reload" | "current") {
    if (flight.current) return;
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      if (action === "current") {
        await onViewCurrent();
        return;
      }
      if (action === "submit") {
        setAttempted(true);
        const originalRequest =
          receipt?.delivery_status === "pending"
            ? receipt.evidence.request
            : null;
        if (!turnId.current)
          turnId.current = originalRequest?.turn_id ?? crypto.randomUUID();
        const response = await client.startNaturalTurn(
          snapshot,
          originalRequest?.original_text ?? text,
          originalRequest?.turn_id ?? turnId.current,
          (originalRequest?.selections?.[0]?.value ?? selection) || undefined,
          originalRequest?.expected_revision_id,
        );
        if (response.schema_version !== "2.0.0")
          throw new Error("Unexpected turn contract");
        setReceipt(response);
      } else {
        const response = await client.naturalTurn();
        if (response.schema_version !== "2.0.0")
          throw new Error("Unexpected turn contract");
        setReceipt(response);
      }
    } catch (e) {
      setError(
        e instanceof ApiError && (e.status === 401 || e.status === 403)
          ? t(
              "Sign in again or check access.",
              "Войдите снова или проверьте доступ.",
            )
          : t(
              "Could not verify server State. Your draft is retained; reload before attempting delivery again.",
              "Не удалось проверить State на сервере. Черновик сохранён; обновите данные перед повторной доставкой.",
            ),
      );
    } finally {
      setBusy(false);
      flight.current = false;
    }
  }

  function appendTranscript(spoken: string) {
    setText((current) => {
      const combined = current.trim()
        ? [current.trimEnd(), spoken].join("\n")
        : spoken;
      return combined.slice(0, 2000);
    });
  }

  const delivered = receipt?.delivered_reply;
  const savedSource = receipt?.evidence.request.original_text;
  return (
    <main className="page enrichment-page studio-first-turn" aria-busy={busy}>
      <Link
        to={`/organizations/${client.organizationId}/projects/${session.project_id}`}
      >
        {t("Sessions", "Сессии")}
      </Link>
      <header className="studio-first-turn-hero">
        <div>
          <p className="eyebrow">
            {t("JEWELAI DESIGN STUDIO", "СТУДИЯ ДИЗАЙНА JEWELAI")}
          </p>
          <h1>{t("Describe your jewelry", "Опишите украшение")}</h1>
        </div>
      </header>
      <p>
        {t(
          "Describe your idea in your own words or use the microphone.",
          "Опишите вашу идею своими словами или используйте микрофон.",
        )}
      </p>
      {!options.model_configured && (
        <p role="status">
          {t(
            "AI conversation is not connected yet. Your description can be saved, but you will receive an automatic response instead of an AI answer.",
            "ИИ-консультант пока не подключён. Описание можно сохранить, но вместо ответа ИИ вы получите автоматическое сообщение.",
          )}
        </p>
      )}
      <div className="studio-first-turn-panel">
        {error && <p role="alert">{error}</p>}
        {!receipt && (
          <form
            className="studio-first-turn-form"
            onSubmit={(event) => {
              event.preventDefault();
              if ((text.trim() || selection) && !attempted) void run("submit");
            }}
          >
            <label>
              {t("Your original description", "Исходное описание")}
              <textarea
                value={text}
                maxLength={2000}
                disabled={busy || attempted}
                onChange={(event) => setText(event.target.value)}
              />
            </label>
            <VoiceRecorder
              api={client.api}
              organizationId={client.organizationId}
              sessionId={client.sessionId}
              language={session.locale}
              disabled={busy || attempted}
              onTranscript={appendTranscript}
            />
            {options.options.length > 0 && (
              <label>
                {t(
                  "Explicit jewelry type (optional)",
                  "Выбранный тип изделия (необязательно)",
                )}
                <select
                  value={selection}
                  disabled={busy || attempted}
                  onChange={(event) => setSelection(event.target.value)}
                >
                  <option value="">
                    {t("No selected type", "Тип не выбран")}
                  </option>
                  {options.options.map((option) => (
                    <option value={option.value} key={option.mapping_id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="studio-first-turn-actions">
              <button
                type="submit"
                disabled={busy || attempted || (!text.trim() && !selection)}
              >
                {busy
                  ? t("Processing…", "Обрабатываем…")
                  : options.model_configured
                    ? t("Send description", "Отправить описание")
                    : t("Save description", "Сохранить описание")}
              </button>
              {error && (
                <button
                  type="button"
                  className="quiet"
                  disabled={busy}
                  onClick={() => void run("reload")}
                >
                  {t("Restore saved data", "Восстановить сохранённые данные")}
                </button>
              )}
              <button
                type="button"
                className="quiet"
                disabled={busy}
                onClick={onClose}
              >
                {t("Cancel", "Отмена")}
              </button>
            </div>
          </form>
        )}
        {receipt && (
          <section
            aria-label={t(
              "Verified first turn",
              "Проверенное первое сообщение",
            )}
          >
            <h2>
              {t(
                "Original request · saved on server",
                "Исходное сообщение · сохранено на сервере",
              )}
            </h2>
            <p style={{ whiteSpace: "pre-wrap" }}>
              {savedSource || t("Typed selection", "Выбор параметра")}
            </p>
            {!receipt.is_current_revision && (
              <p role="status">
                {t(
                  "Historical turn: the current State has since changed.",
                  "Историческое сообщение: актуальный State уже изменился.",
                )}
              </p>
            )}
            <h2>{t("Saved design brief", "Сохранённое описание дизайна")}</h2>
            <p style={{ whiteSpace: "pre-wrap" }}>{receipt.current_brief}</p>
            {receipt.delivery_status === "pending" ? (
              <p role="status">
                {t(
                  "Your input and State were committed. The reply is pending. Use Retry to resume delivery without committing State again.",
                  "Сообщение и State сохранены. Ответ ожидается. Нажмите «Повторить», чтобы завершить доставку без повторного сохранения State.",
                )}
              </p>
            ) : delivered ? (
              <>
                <h2>
                  {delivered.origin === "model"
                    ? t("Saved model reply", "Сохранённый ответ модели")
                    : t("Saved fallback reply", "Сохранённый резервный ответ")}
                </h2>
                <p style={{ whiteSpace: "pre-wrap" }}>{delivered.text}</p>
              </>
            ) : (
              <p role="alert">
                {t(
                  "Reply receipt is unavailable.",
                  "Сохранённый ответ недоступен.",
                )}
              </p>
            )}
            <p>
              {t("Current revision", "Текущая ревизия")}:{" "}
              {receipt.current_revision.revision_id}
            </p>
          </section>
        )}
        {attempted && !receipt && text && (
          <section
            aria-label={t(
              "Unverified local draft",
              "Непроверенный локальный черновик",
            )}
          >
            <h2>
              {t("Unverified local draft", "Непроверенный локальный черновик")}
            </h2>
            <p style={{ whiteSpace: "pre-wrap" }}>{text}</p>
          </section>
        )}
        {((attempted && !receipt) ||
          receipt?.delivery_status === "pending") && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run("submit")}
          >
            {t("Retry same turn (same identity)", "Повторить ту же операцию")}
          </button>
        )}
        {receipt && error && (
          <div className="studio-first-turn-actions">
            <button
              type="button"
              className="quiet"
              disabled={busy}
              onClick={() => void run("reload")}
            >
              {t("Restore saved data", "Восстановить сохранённые данные")}
            </button>
          </div>
        )}
        {receipt && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run("current")}
          >
            {t("Continue with my design", "Продолжить работу над дизайном")}
          </button>
        )}
      </div>
    </main>
  );
}
