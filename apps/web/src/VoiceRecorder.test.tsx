import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./api";
import { VoiceRecorder } from "./VoiceRecorder";

const tracks = { stop: vi.fn() };
const capture = { getTracks: () => [tracks] };
class Recorder {
  static instances: Recorder[] = [];
  static isTypeSupported = (type: string) => type.startsWith("audio/webm");
  state = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly stream: typeof capture) {
    Recorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.onstop?.();
  }
}
const getUserMedia = vi.fn();
beforeEach(() => {
  Recorder.instances = [];
  tracks.stop.mockClear();
  getUserMedia.mockReset().mockResolvedValue(capture);
  vi.stubGlobal("MediaRecorder", Recorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fixture(language: "en" | "ru" = "en") {
  const api = new ApiClient(
    "https://api.example.test",
    async () => "test-token",
    async () => {},
  );
  const request = vi.spyOn(api, "request").mockResolvedValue({
    schema_version: "1.0.0",
    status: "transcribed",
    text: language === "en" ? "A gold ring." : "Золотое кольцо.",
  });
  const onTranscript = vi.fn();
  const view = render(
    <VoiceRecorder
      api={api}
      organizationId="org"
      sessionId="session"
      language={language}
      disabled={false}
      onTranscript={onTranscript}
    />,
  );
  return { ...view, request, onTranscript };
}
async function start() {
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(Recorder.instances).toHaveLength(1));
}
function finish(bytes = "synthetic audio") {
  act(() => {
    Recorder.instances[0]!.ondataavailable?.({ data: new Blob([bytes]) });
  });
  fireEvent.click(screen.getByRole("button"));
}

describe("editable speech input", () => {
  it.each(["en", "ru"] as const)(
    "records %s and returns editable text without submitting PE",
    async (language) => {
      const { request, onTranscript } = fixture(language);
      await start();
      expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
      finish();
      await waitFor(() => expect(onTranscript).toHaveBeenCalledOnce());
      expect(onTranscript).toHaveBeenCalledWith(
        language === "en" ? "A gold ring." : "Золотое кольцо.",
      );
      expect(request).toHaveBeenCalledOnce();
      const [path, options] = request.mock.calls[0]!;
      expect(path).toBe(
        `/sessions/session/transcriptions?language=${language}`,
      );
      expect(options?.organizationId).toBe("org");
      expect(options?.body).toBeInstanceOf(FormData);
      expect(tracks.stop).toHaveBeenCalled();
    },
  );
  it("reports denied microphone without any HTTP request", async () => {
    getUserMedia.mockRejectedValueOnce(
      new DOMException("denied", "NotAllowedError"),
    );
    const { request } = fixture();
    fireEvent.click(screen.getByRole("button"));
    expect(
      await screen.findByText("Microphone unavailable"),
    ).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
  it("does not transmit empty recording", async () => {
    const { request } = fixture();
    await start();
    finish("");
    expect(
      screen.getByText("Recording is empty or too large"),
    ).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
  it("shows busy state and safe fallback after unavailable STT", async () => {
    const { request, onTranscript } = fixture();
    let reject!: (reason: Error) => void;
    request.mockImplementationOnce(
      () =>
        new Promise((_, fail) => {
          reject = fail;
        }),
    );
    await start();
    finish();
    expect(screen.getByRole("button")).toBeDisabled();
    await act(async () => reject(new Error("private upstream details")));
    expect(
      await screen.findByText("Transcription unavailable. You can still type."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("private upstream details"),
    ).not.toBeInTheDocument();
    expect(onTranscript).not.toHaveBeenCalled();
  });
  it("handles silence without adding text", async () => {
    const { request, onTranscript } = fixture();
    request.mockResolvedValueOnce({
      schema_version: "1.0.0",
      status: "silence",
      text: "",
    });
    await start();
    finish();
    expect(await screen.findByText("No speech detected")).toBeInTheDocument();
    expect(onTranscript).not.toHaveBeenCalled();
  });
  it("stops microphone and ignores data after unmount/session change", async () => {
    const { unmount, request, onTranscript } = fixture();
    await start();
    unmount();
    expect(tracks.stop).toHaveBeenCalled();
    expect(Recorder.instances[0]!.state).toBe("inactive");
    expect(request).not.toHaveBeenCalled();
    expect(onTranscript).not.toHaveBeenCalled();
  });
  it("does not transcribe a failed recording", async () => {
    const { request } = fixture();
    await start();
    act(() => Recorder.instances[0]!.onerror?.());
    expect(screen.getByText("Audio recording failed")).toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
});
