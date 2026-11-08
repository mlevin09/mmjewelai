import { useEffect, useRef, useState } from "react";
import { ApiClient } from "./api";

type SpeechResult = {
  schema_version: string;
  status: "transcribed" | "silence";
  text: string;
};

const MAX_AUDIO_BYTES = 10 * 1024 * 1024;
const MAX_RECORDING_MS = 60_000;
const RECORDING_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/ogg",
];

export function VoiceRecorder({
  api,
  organizationId,
  sessionId,
  language,
  disabled,
  onTranscript,
}: {
  api: ApiClient;
  organizationId: string;
  sessionId: string;
  language: "ru" | "en";
  disabled: boolean;
  onTranscript: (text: string) => void;
}) {
  const [recording, setRecording] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [message, setMessage] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = useRef(true);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      request.current?.abort();
      if (timeout.current) clearTimeout(timeout.current);
      recorder.current?.stream.getTracks().forEach((track) => track.stop());
      if (recorder.current?.state === "recording") recorder.current.stop();
    };
  }, []);

  const available =
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    RECORDING_TYPES.some((type) => MediaRecorder.isTypeSupported(type));

  function stop() {
    if (timeout.current) clearTimeout(timeout.current);
    if (recorder.current?.state === "recording") recorder.current.stop();
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    setRecording(false);
  }

  async function start() {
    if (!available || disabled || requesting || recording || transcribing)
      return;
    setRequesting(true);
    setMessage("");
    let capture: MediaStream | null = null;
    try {
      const mimeType = RECORDING_TYPES.find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      if (!mimeType) throw new Error("unsupported_codec");
      capture = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!active.current) {
        capture.getTracks().forEach((track) => track.stop());
        return;
      }
      const instance = new MediaRecorder(capture, { mimeType });
      const parts: Blob[] = [];
      let recordingFailed = false;
      recorder.current = instance;
      stream.current = capture;
      instance.ondataavailable = (event) => {
        if (event.data.size) parts.push(event.data);
      };
      instance.onerror = () => {
        recordingFailed = true;
        if (active.current)
          setMessage(
            language === "ru"
              ? "Ошибка записи звука"
              : "Audio recording failed",
          );
        stop();
      };
      instance.onstop = () => {
        capture?.getTracks().forEach((track) => track.stop());
        if (!active.current || recordingFailed) return;
        setRecording(false);
        const audio = new Blob(parts, { type: mimeType.split(";")[0] });
        if (!audio.size || audio.size > MAX_AUDIO_BYTES) {
          setMessage(
            language === "ru"
              ? "Запись пуста или слишком велика"
              : "Recording is empty or too large",
          );
          return;
        }
        const form = new FormData();
        form.append("audio", audio, "speech.webm");
        setTranscribing(true);
        const controller = new AbortController();
        request.current = controller;
        void api
          .request<SpeechResult>(
            `/sessions/${sessionId}/transcriptions?language=${language}`,
            {
              method: "POST",
              body: form,
              organizationId,
              signal: controller.signal,
            },
          )
          .then((result) => {
            if (!active.current) return;
            if (
              result.schema_version !== "1.0.0" ||
              !["transcribed", "silence"].includes(result.status) ||
              typeof result.text !== "string" ||
              result.text.length > 8192
            ) {
              throw new Error("invalid_transcription");
            }
            if (result.text.trim()) onTranscript(result.text.trim());
            else
              setMessage(
                language === "ru" ? "Речь не распознана" : "No speech detected",
              );
          })
          .catch(() => {
            if (active.current)
              setMessage(
                language === "ru"
                  ? "Не удалось распознать речь. Текст можно ввести вручную."
                  : "Transcription unavailable. You can still type.",
              );
          })
          .finally(() => {
            if (active.current) setTranscribing(false);
          });
      };
      instance.start();
      setRecording(true);
      timeout.current = setTimeout(() => stop(), MAX_RECORDING_MS);
    } catch {
      capture?.getTracks().forEach((track) => track.stop());
      if (active.current)
        setMessage(
          language === "ru"
            ? "Не удалось открыть микрофон"
            : "Microphone unavailable",
        );
    } finally {
      if (active.current) setRequesting(false);
    }
  }

  return (
    <div className="voice-recorder">
      <button
        type="button"
        className="quiet"
        disabled={disabled || requesting || transcribing || !available}
        aria-label={
          recording
            ? language === "ru"
              ? "Остановить запись"
              : "Stop recording"
            : language === "ru"
              ? "Голосовой ввод"
              : "Voice input"
        }
        aria-pressed={recording}
        onClick={() => (recording ? stop() : void start())}
      >
        {transcribing
          ? language === "ru"
            ? "Распознаём…"
            : "Transcribing…"
          : recording
            ? language === "ru"
              ? "■ Остановить"
              : "■ Stop"
            : language === "ru"
              ? "🎙 Голосовой ввод"
              : "🎙 Voice input"}
      </button>
      <span className="voice-recorder-hint" role="status" aria-live="polite">
        {message ||
          (recording
            ? language === "ru"
              ? "Идёт запись (до 60 секунд)"
              : "Recording (up to 60 seconds)"
            : !available
              ? language === "ru"
                ? "Браузер не поддерживает запись WebM/Ogg"
                : "Browser does not support WebM/Ogg recording"
              : "")}
      </span>
    </div>
  );
}
