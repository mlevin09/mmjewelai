import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { ApiClient } from "./api";
import { EnrichmentWorkspace } from "./EnrichmentWorkspace";
import { server } from "./test/server";

afterEach(cleanup);
const root = "http://localhost:8000";
const prefix = `${root}/v1/sessions/session/prompt-enrichment`;
function setup(locale = "en", questions = "2.0.0", rules = "2.0.0") {
  let original = "";
  let saved = false;
  let historical = false;
  let forbidden = false;
  let failedRead: "receipt" | "conversation" | null = null;
  const commands: unknown[] = [];
  const reply =
    locale === "ru"
      ? "Принято: серьги. Остальные слова сохранены, но не приняты как параметры."
      : "Accepted: earrings. Remaining words retained, not accepted as parameters.";
  const receipt = () => ({
    schema_version: "1.0.0",
    receipt: {
      schema_version: "1.0.0",
      binding: { message_id: "m1", result_revision_id: "r2" },
      reply_origin: "deterministic_fallback",
      reply_text: reply,
    },
    is_current_revision: !historical,
    current_revision_id: historical ? "r3" : "r2",
  });
  server.use(
    http.get(`${root}/sessions/session`, () =>
      HttpResponse.json({
        session_id: "session",
        project_id: "project",
        role_id: "retail_client",
        locale,
        artifacts: { questions, rules },
      }),
    ),
    http.get(`${prefix}/conversation`, () => {
      if (saved && failedRead === "conversation")
        return HttpResponse.json({ error: "read_failure" }, { status: 503 });
      return HttpResponse.json({
        schema_version: "1.0.0",
        session_id: "session",
        state: historical
          ? {
              schema_version: "3.0.0",
              retained_base: "F",
              extension_profile: null,
              continuation_enabled: false,
              current_frame: { revision_id: "r3" },
              questions: [],
              status: "clarification_required",
              description: { text: "Current platinum earrings." },
              protection_projection: { roots: [], pending_requests: [] },
              native_frontier: null,
            }
          : null,
        revision: {
          revision_id: historical ? "r3" : saved ? "r2" : "r1",
          design: historical
            ? {
                metal: {
                  material: {
                    availability: "value",
                    value: "platinum",
                    origin: "explicit",
                    confirmed: false,
                    locked: false,
                  },
                },
              }
            : {},
        },
        events: saved
          ? [
              {
                event_id: "e1",
                kind: "user",
                message_id: "m1",
                text: original,
              },
              ...(historical
                ? [
                    {
                      event_id: "e2",
                      kind: "user",
                      message_id: "m2",
                      text: "Use platinum for the metal material.",
                    },
                  ]
                : []),
            ]
          : [],
      });
    }),
    http.get(`${prefix}/first-turn`, () =>
      forbidden
        ? HttpResponse.json(
            { error: "forbidden", detail: "Denied" },
            { status: 403 },
          )
        : saved && failedRead === "receipt"
          ? HttpResponse.json({ error: "read_failure" }, { status: 503 })
          : saved
            ? HttpResponse.json(receipt())
            : HttpResponse.json(
                { error: "not_found", detail: "No receipt" },
                { status: 404 },
              ),
    ),
    http.post(`${prefix}/first-turn/messages`, async ({ request }) => {
      expect(request.headers.get("X-Organization-ID")).toBe("org");
      const body = (await request.json()) as { content: string };
      original = body.content;
      commands.push(body);
      return HttpResponse.json({ message_id: "m1" });
    }),
    http.post(`${root}/sessions/session/messages`, () => {
      throw new Error(
        "Pilot must not call the legacy trimming Message endpoint",
      );
    }),
    http.post(`${prefix}/first-turn`, async ({ request }) => {
      expect(request.headers.get("X-Organization-ID")).toBe("org");
      commands.push(await request.json());
      saved = true;
      return HttpResponse.json(receipt(), { status: 201 });
    }),
    http.post(`${prefix}/initial`, () => {
      throw new Error("Pilot must not call legacy initial");
    }),
    http.get(`${prefix}/completions/current`, () =>
      HttpResponse.json({ error: "not_found" }, { status: 404 }),
    ),
  );
  const api = new ApiClient(root, async () => "test-token", vi.fn());
  const mount = () =>
    render(
      <MemoryRouter>
        <EnrichmentWorkspace
          api={api}
          organizationId="org"
          sessionId="session"
        />
      </MemoryRouter>,
    );
  return {
    mount,
    commands,
    reply,
    historical: () => {
      historical = true;
    },
    deny: () => {
      forbidden = true;
    },
    failRead: (kind: typeof failedRead) => {
      failedRead = kind;
    },
  };
}
describe("isolated first-turn pilot", () => {
  it.each([
    ["en", "receipt"],
    ["ru", "receipt"],
    ["en", "conversation"],
    ["ru", "conversation"],
  ] as const)(
    "labels an unverified draft after %s %s read failure",
    async (locale, failed) => {
      const f = setup(locale);
      f.failRead(failed);
      f.mount();
      fireEvent.click(
        await screen.findByRole("button", {
          name: /Open text-only|Открыть текстовый/,
        }),
      );
      const raw =
        locale === "ru"
          ? " \tХочу серьги из золота\n "
          : " \tI want gold earrings\n ";
      fireEvent.change(screen.getByRole("textbox"), { target: { value: raw } });
      fireEvent.click(
        screen.getByRole("button", {
          name: /Save first message|Сохранить первое сообщение/,
        }),
      );
      await screen.findByRole("alert");
      const saved = screen.getByRole("region", {
        name: /Saved first turn|Сохранённое первое сообщение/,
      });
      expect(
        within(saved).queryByText(raw, { normalizer: (value) => value }),
      ).not.toBeInTheDocument();
      const draft = screen.getByRole("region", {
        name: /Unverified local draft|Непроверенный локальный черновик/,
      });
      expect(
        within(draft).getByText(raw, { normalizer: (value) => value })
          .textContent,
      ).toBe(raw);
      f.failRead(null);
      fireEvent.click(
        screen.getByRole("button", {
          name: /Reload saved reply|Обновить сохранённый ответ/,
        }),
      );
      await waitFor(() =>
        expect(
          screen.queryByRole("region", {
            name: /Unverified local draft|Непроверенный локальный черновик/,
          }),
        ).not.toBeInTheDocument(),
      );
      expect(
        within(saved).getByText(raw, { normalizer: (value) => value })
          .textContent,
      ).toBe(raw);
      expect(f.commands).toHaveLength(2);
    },
  );
  it.each(["en", "ru"])(
    "opens current state and history from a historical %s receipt",
    async (locale) => {
      const f = setup(locale);
      const initial = f.mount();
      fireEvent.click(
        await screen.findByRole("button", {
          name: /Open text-only|Открыть текстовый/,
        }),
      );
      fireEvent.change(screen.getByRole("textbox"), {
        target: { value: "I want gold earrings" },
      });
      fireEvent.click(
        screen.getByRole("button", {
          name: /Save first message|Сохранить первое сообщение/,
        }),
      );
      await screen.findByText(f.reply);
      initial.unmount();
      f.historical();
      f.mount();
      await screen.findByText(f.reply);
      expect(screen.getByRole("status")).toHaveTextContent(
        /Historical reply|Исторический ответ/,
      );
      f.failRead("conversation");
      fireEvent.click(
        screen.getByRole("button", {
          name: /View current state and history|Открыть актуальное состояние и историю/,
        }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        /Could not load current state|Не удалось загрузить актуальное состояние/,
      );
      expect(
        screen.queryByText("Current platinum earrings."),
      ).not.toBeInTheDocument();
      f.failRead(null);
      await waitFor(() =>
        expect(
          screen.getByRole("button", {
            name: /View current state and history|Открыть актуальное состояние и историю/,
          }),
        ).toBeEnabled(),
      );
      fireEvent.click(
        screen.getByRole("button", {
          name: /View current state and history|Открыть актуальное состояние и историю/,
        }),
      );
      expect(
        await screen.findByText("Current platinum earrings."),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("list", {
          name: /Saved conversation|Сохранённая беседа/,
        }),
      ).toHaveTextContent("Use platinum for the metal material.");
      fireEvent.click(
        screen.getByRole("button", {
          name: /View saved first-turn reply|Открыть сохранённый ответ первого сообщения/,
        }),
      );
      expect(await screen.findByText(f.reply)).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(
        /Historical reply|Исторический ответ/,
      );
      expect(f.commands).toHaveLength(2);
    },
  );
  it.each(["en", "ru"])(
    "sends exact %s raw input once and reloads retained fallback",
    async (locale) => {
      const f = setup(locale);
      const view = f.mount();
      const open =
        locale === "ru"
          ? "Открыть текстовый пилот первого сообщения"
          : "Open text-only first-turn pilot";
      fireEvent.click(await screen.findByRole("button", { name: open }));
      expect(screen.queryByLabelText("Center stone")).not.toBeInTheDocument();
      const raw =
        locale === "ru"
          ? " \t\nХочу серьги из белого золота с двумя сапфирами\n\t "
          : " \t\nI want white gold earrings with two sapphires\n\t ";
      fireEvent.change(screen.getByRole("textbox"), { target: { value: raw } });
      const send = screen.getByRole("button", {
        name:
          locale === "ru" ? "Сохранить первое сообщение" : "Save first message",
      });
      fireEvent.click(send);
      fireEvent.click(send);
      expect(await screen.findByText(f.reply)).toBeInTheDocument();
      expect(f.commands).toEqual([
        { schema_version: "1.0.0", expected_revision_id: "r1", content: raw },
        {
          schema_version: "1.0.0",
          message_id: "m1",
          expected_revision_id: "r1",
        },
      ]);
      expect(
        screen.getByText(raw, { normalizer: (value) => value }).textContent,
      ).toBe(raw);
      view.unmount();
      f.historical();
      f.mount();
      expect(await screen.findByText(f.reply)).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(
        locale === "ru" ? "Исторический ответ" : "Historical reply",
      );
      expect(
        screen.getByRole("heading", {
          name:
            locale === "ru"
              ? "Сохранённый ответ · резервный режим"
              : "Saved reply · fallback mode",
        }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", {
          name: /Save first message|Сохранить первое/,
        }),
      ).not.toBeInTheDocument();
      expect(f.commands).toHaveLength(2);
    },
  );
  it("cancel returns to unchanged legacy form without writes", async () => {
    const f = setup();
    f.mount();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open text-only first-turn pilot",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel pilot" }));
    expect(screen.getByLabelText("Center stone")).toBeInTheDocument();
    expect(f.commands).toEqual([]);
  });
  it("does not offer pilot for retained L", async () => {
    setup("en", "1.0.0").mount();
    await screen.findByLabelText("Center stone");
    expect(
      screen.queryByRole("button", { name: "Open text-only first-turn pilot" }),
    ).not.toBeInTheDocument();
  });
  it("does not offer pilot without the complete retained F artifact pair", async () => {
    setup("en", "2.0.0", "1.0.0").mount();
    await screen.findByLabelText("Center stone");
    expect(
      screen.queryByRole("button", { name: "Open text-only first-turn pilot" }),
    ).not.toBeInTheDocument();
  });
  it("does not disguise forbidden receipt reads as legacy absence", async () => {
    const f = setup();
    f.deny();
    f.mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to open",
    );
    expect(
      screen.queryByRole("button", { name: "Open text-only first-turn pilot" }),
    ).not.toBeInTheDocument();
  });
  it("keeps input and prevents duplicate submission after uncertain transport", async () => {
    const f = setup();
    server.use(http.post(`${prefix}/first-turn`, () => HttpResponse.error()));
    f.mount();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open text-only first-turn pilot",
      }),
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "I want earrings" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save first message" }));
    await screen.findByRole("alert");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Reload saved reply" }),
      ).toBeEnabled(),
    );
    expect(screen.getByRole("textbox")).toHaveValue("I want earrings");
    expect(
      screen.getByRole("button", { name: "Save first message" }),
    ).toBeDisabled();
    expect(f.commands).toHaveLength(1);
  });
});
