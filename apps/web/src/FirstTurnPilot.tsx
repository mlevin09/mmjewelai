import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "./api";
import type {
  Conversation,
  EnrichmentClient,
  FirstTurnRead,
} from "./enrichment";
import type { Session } from "./types";

/** Explicit first-turn pilot, isolated from guided input and later-story commands. */
export function FirstTurnPilot({
  client,
  session,
  snapshot,
  saved,
  onClose,
  onViewCurrent,
}: {
  client: EnrichmentClient;
  session: Session;
  snapshot: Conversation;
  saved: FirstTurnRead | null;
  onClose: () => void;
  onViewCurrent: () => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [receipt, setReceipt] = useState(saved);
  const [conversation, setConversation] = useState(snapshot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [attempted, setAttempted] = useState(false);
  const flight = useRef(false);
  const ru = session.locale === "ru";
  const t = (en: string, russian: string) => (ru ? russian : en);
  async function reload() {
    const result = await client.firstTurn();
    const current = await client.read();
    setReceipt(result);
    setConversation(current);
  }
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
        // Preserve exact raw input, including whitespace. Do not synthesize intent.
        const result = await client.startFirstTurn(conversation, text);
        setReceipt(result);
      }
      await reload();
    } catch (e) {
      setError(
        e instanceof ApiError && (e.status === 401 || e.status === 403)
          ? t(
              "Sign in again or check your access.",
              "Войдите снова или проверьте доступ.",
            )
          : action === "current"
            ? t(
                "Could not load current state and history. The saved reply remains here; try again.",
                "Не удалось загрузить актуальное состояние и историю. Сохранённый ответ остаётся здесь; повторите попытку.",
              )
            : t(
                "Could not verify the saved reply. Your input is kept here. Reload to check server state; this pilot does not automatically resend.",
                "Не удалось проверить сохранённый ответ. Ввод остаётся здесь. Обновите данные сервера; пилот не отправляет сообщение повторно автоматически.",
              ),
      );
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }
  const source =
    receipt &&
    conversation.events.find(
      (e) =>
        e.kind === "user" &&
        e.message_id === receipt.receipt.binding.message_id,
    );
  return (
    <main className="page enrichment-page" aria-busy={busy}>
      <Link
        to={`/organizations/${client.organizationId}/projects/${session.project_id}`}
      >
        {t("Sessions", "Сессии")}
      </Link>
      <h1>{t("First-turn text pilot", "Текстовый пилот первого сообщения")}</h1>
      <p>
        {t(
          "One original message and its saved reply. Deterministic fallback, not a model response. Guided fields, clarification and final brief are outside this pilot.",
          "Одно исходное сообщение и сохранённый ответ. Детерминированный резервный режим, не ответ модели. Поля выбора, уточнения и финальный brief вне этого пилота.",
        )}
      </p>
      {error && <p role="alert">{error}</p>}
      {!receipt && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim() && !attempted) void run("submit");
          }}
        >
          <label>
            {t("Original request", "Исходный запрос")}
            <textarea
              value={text}
              maxLength={2000}
              disabled={busy || attempted}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <button type="submit" disabled={busy || attempted || !text.trim()}>
            {t("Save first message", "Сохранить первое сообщение")}
          </button>
          {!attempted && (
            <button type="button" disabled={busy} onClick={onClose}>
              {t("Cancel pilot", "Отменить пилот")}
            </button>
          )}
        </form>
      )}
      {receipt && (
        <section
          aria-label={t("Saved first turn", "Сохранённое первое сообщение")}
        >
          <h2>{t("Original request", "Исходный запрос")}</h2>
          <p style={{ whiteSpace: "pre-wrap" }}>
            {source
              ? source.text
              : t(
                  "The saved source message has not been read back in this view.",
                  "Сохранённое исходное сообщение ещё не прочитано с сервера в этом представлении.",
                )}
          </p>
          <h2>
            {t(
              "Saved reply · fallback mode",
              "Сохранённый ответ · резервный режим",
            )}
          </h2>
          {!receipt.is_current_revision && (
            <p role="status">
              {t(
                "Historical reply, not the current design state.",
                "Исторический ответ, не текущее состояние дизайна.",
              )}
            </p>
          )}
          <p style={{ whiteSpace: "pre-wrap" }}>{receipt.receipt.reply_text}</p>
          <p>
            {t("Current revision", "Текущая ревизия")}:{" "}
            {receipt.current_revision_id}
          </p>
          <p>
            {t(
              "No follow-up or final confirmation is included in this pilot.",
              "Продолжение и финальное подтверждение не входят в пилот.",
            )}
          </p>
        </section>
      )}
      {receipt && !source && text && (
        <section
          aria-label={t(
            "Unverified local draft",
            "Непроверенный локальный черновик",
          )}
        >
          <h2>
            {t("Unverified local draft", "Непроверенный локальный черновик")}
          </h2>
          <p>
            {t(
              "This is your local input, not a message read back from the server.",
              "Это локально введённый текст, а не сообщение, прочитанное с сервера.",
            )}
          </p>
          <p style={{ whiteSpace: "pre-wrap" }}>{text}</p>
        </section>
      )}
      {receipt && (
        <button
          type="button"
          disabled={busy}
          onClick={() => void run("current")}
        >
          {t(
            "View current state and history",
            "Открыть актуальное состояние и историю",
          )}
        </button>
      )}
      <button type="button" disabled={busy} onClick={() => void run("reload")}>
        {t("Reload saved reply", "Обновить сохранённый ответ")}
      </button>
    </main>
  );
}
