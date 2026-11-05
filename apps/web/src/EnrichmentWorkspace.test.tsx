import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./api";
import { EnrichmentWorkspace } from "./EnrichmentWorkspace";
import {
  EnrichmentClient,
  type Conversation,
  type EnrichmentState,
} from "./enrichment";
import { server } from "./test/server";

const root = "http://localhost:8000";
afterEach(cleanup);
const prefix = `${root}/v1/sessions/session/prompt-enrichment`;
const frame = {
  revision_id: "r1",
  revision_sha256: "a".repeat(64),
  enrichment_cycle_id: "c1",
  enrichment_cycle_number: 1,
  enrichment_result_hash: "b".repeat(64),
  plan_id: "p1",
  plan_hash: "c".repeat(64),
  history_root_sha256: "d".repeat(64),
};
const state: EnrichmentState = {
  schema_version: "3.0.0",
  retained_base: "F",
  extension_profile: null,
  continuation_enabled: false,
  current_frame: frame,
  questions: [],
  status: "final_output_ready_with_unresolved",
  description: { text: "A white gold ring with an oval diamond." },
  protection_projection: { roots: [], pending_requests: [] },
  native_frontier: null,
};
function fixture(
  started = false,
  base: "L" | "F" = "F",
  locale: "en" | "ru" = "en",
) {
  const current = { ...structuredClone(state), retained_base: base };
  let data = {
    schema_version: "1.0.0",
    session_id: "session",
    events: [],
    state: started ? current : null,
    revision: {
      schema_version: "1.0.0",
      revision_id: "r1",
      design: { metal: { material: null }, center_stone: { shape: null } },
    },
  } as unknown as Conversation;
  let stored = "";
  const commands: { route: string; body: Record<string, unknown> }[] = [];
  const api = new ApiClient(
    root,
    async () => "synthetic-token",
    async () => undefined,
  );
  server.use(
    http.get(`${root}/sessions/session`, () =>
      HttpResponse.json({
        session_id: "session",
        project_id: "project",
        role_id: "retail_client",
        locale,
        artifacts: { questions: base === "F" ? "2.0.0" : "1.0.0" },
      }),
    ),
    http.get(`${prefix}/conversation`, ({ request }) => {
      expect(request.headers.get("X-Organization-ID")).toBe("org");
      return HttpResponse.json(data);
    }),
    http.get(`${prefix}/final-output`, ({ request }) => {
      expect(request.headers.get("If-Match")).toBe(
        data.state?.current_frame.history_root_sha256,
      );
      return HttpResponse.json({
        description: data.state?.description,
        internal_final_prompt: {
          prompt_text: "The actual server prompt, without client additions.",
          readiness: "READY_WITH_UNRESOLVED",
        },
      });
    }),
    http.post(`${root}/sessions/session/messages`, async ({ request }) => {
      stored = ((await request.json()) as { content: string }).content;
      const mid = `m${data.events.length}`;
      data.events.push({
        event_id: mid,
        message_id: mid,
        kind: "user",
        created_at: "2026-11-05T00:00:00Z",
        text: stored,
        outcome: null,
      });
      return HttpResponse.json({ message_id: mid }, { status: 201 });
    }),
    http.post(`${prefix}/:route`, async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      commands.push({ route: String(params.route), body });
      data.state ??= current;
      if (params.route === "initial") {
        data.revision.design.metal.material = {
          availability: "value",
          value: "gold",
          origin: "explicit",
          confirmed: false,
          locked: false,
        };
        data.revision.design.center_stone.shape = {
          availability: "value",
          value: "oval",
          origin: "explicit",
          confirmed: false,
          locked: false,
        };
      }
      if (stored.includes("platinum")) {
        data.revision.design.metal.material = {
          availability: "value",
          value: "platinum",
          origin: "explicit",
          confirmed: false,
          locked: false,
        };
        data.state.description.text = "A platinum ring with an oval diamond.";
      }
      if (stored.includes("Keep"))
        data.state.protection_projection.roots.push({
          source_wording: "Keep the center stone unchanged.",
        });
      data.events.push({
        event_id: `d${commands.length}`,
        kind: "decision",
        created_at: "2026-11-05T00:00:01Z",
        text: "APPLIED",
        outcome: "APPLIED",
        message_id: String(body.message_id),
      });
      return HttpResponse.json(
        { state: data.state },
        { status: params.route === "initial" ? 201 : 200 },
      );
    }),
  );
  const view = () =>
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
    view,
    api,
    commands,
    get data() {
      return data;
    },
    set data(value: Conversation) {
      data = value;
    },
  };
}
async function send(text: string) {
  fireEvent.change(screen.getByLabelText("Your message"), {
    target: { value: text },
  });
  await userEvent.click(screen.getByRole("button", { name: "Send message" }));
  await screen.findByRole("button", { name: "Send message" });
}

describe("Prompt Enrichment workspace", () => {
  it("keeps writes single-flight and hides the previous prompt while a change is pending", async () => {
    const f = fixture(true);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let posts = 0;
    server.use(
      http.post(`${prefix}/corrections`, async () => {
        posts++;
        await gate;
        return HttpResponse.json({});
      }),
    );
    f.view();
    await screen.findByRole("button", { name: "Copy full prompt" });
    fireEvent.change(screen.getByLabelText("Your message"), {
      target: { value: "A gold ring." },
    });
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(
      await screen.findByRole("button", { name: "Processing…" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Your message")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Copy full prompt" }),
    ).not.toBeInTheDocument();
    fireEvent.submit(screen.getByLabelText("Your message").closest("form")!);
    release();
    await screen.findByRole("button", { name: "Send message" });
    expect(posts).toBe(1);
  });
  it("uses the native L contract and RU composer without changing the user's text", async () => {
    const f = fixture(false, "L", "ru");
    f.view();
    const input = await screen.findByLabelText("Ваше сообщение");
    fireEvent.change(input, {
      target: { value: "Кольцо из белого золота с oval diamond." },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Отправить сообщение" }),
    );
    await waitFor(() => expect(f.commands).toHaveLength(1));
    expect(f.commands[0]?.body).not.toHaveProperty("schema_version");
    expect(f.commands[0]?.body).toMatchObject({
      expected_revision_id: frame.revision_id,
      message_id: "m0",
    });
    expect(f.data.events[0]?.text).toBe(
      "Кольцо из белого золота с oval diamond.",
    );
  });
  it("keeps the full prompt selectable when clipboard permission is denied", async () => {
    userEvent.setup();
    const f = fixture(true);
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(
      new Error("Synthetic clipboard denial"),
    );
    f.view();
    await userEvent.click(
      await screen.findByRole("button", { name: "Copy full prompt" }),
    );
    expect(
      await screen.findByText("Copy unavailable — select the text above."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Internal Final Prompt")).toHaveValue(
      "The actual server prompt, without client additions.",
    );
  });
  it("uses actual scoped commands for initial/corrections/KEEP, restores history and copies only server output", async () => {
    userEvent.setup();
    const f = fixture();
    const view = f.view();
    await screen.findByLabelText("Your message");
    await send("I want a white gold ring with an oval diamond.");
    await userEvent.click(screen.getByText(/Message history/));
    expect(
      within(screen.getByLabelText("Saved conversation")).getByText(
        "Your message",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("You · stored message")).not.toBeInTheDocument();
    expect(f.commands[0]).toMatchObject({
      route: "initial",
      body: { schema_version: "2.0.0", expected_revision_id: "r1" },
    });
    await send("Change the metal to platinum.");
    expect(f.commands[1]).toMatchObject({
      route: "corrections",
      body: {
        schema_version: "2.0.0",
        expected_enrichment_result_hash: frame.enrichment_result_hash,
        expected_clarification_plan_hash: frame.plan_hash,
      },
    });
    await send("Keep the center stone unchanged. Add a delicate band.");
    const panel = screen.getByRole("complementary", { name: "Current design" });
    expect(within(panel).getByText("platinum")).toBeInTheDocument();
    expect(within(panel).getByText("oval")).toBeInTheDocument();
    expect(
      within(panel).getByText(/Confirmed and protected choices are preserved/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Evaluate design")).not.toBeInTheDocument();
    const clipboard = vi
      .spyOn(navigator.clipboard, "writeText")
      .mockResolvedValue();
    await userEvent.click(
      screen.getByRole("button", { name: "Copy full prompt" }),
    );
    expect(clipboard).toHaveBeenCalledWith(
      "The actual server prompt, without client additions.",
    );
    view.unmount();
    f.view();
    expect(
      await screen.findByText(
        "Keep the center stone unchanged. Add a delicate band.",
      ),
    ).toBeInTheDocument();
    await send("One more detail.");
    expect(f.commands).toHaveLength(4);
    expect(
      screen.getByRole("heading", { name: "Create your jewelry" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Your message")).toBeInTheDocument();
  });
  it("does not invent output and preserves the draft on stale CAS; sends no duplicate command", async () => {
    const f = fixture(true);
    let posts = 0;
    server.use(
      http.get(`${prefix}/final-output`, () =>
        HttpResponse.json(
          {
            error: "final_output_blocked",
            detail: "An offered clarification is unresolved",
          },
          { status: 409 },
        ),
      ),
      http.post(`${prefix}/corrections`, () => {
        posts++;
        return HttpResponse.json(
          { error: "stale_revision", detail: "Revision changed" },
          { status: 409 },
        );
      }),
    );
    f.view();
    await screen.findByLabelText("Your message");
    expect(
      await screen.findByText(/A few design details still need your input/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Copy full prompt" }),
    ).not.toBeInTheDocument();
    await send("Make a correction.");
    expect(screen.getByRole("alert")).toHaveTextContent("stale_revision");
    expect(screen.getByLabelText("Your message")).toHaveValue(
      "Make a correction.",
    );
    expect(posts).toBe(1);
  });
  it("renders only server-offered clarification choices and exact F option IDs", async () => {
    const f = fixture(true);
    f.data.state!.questions = [
      {
        question_kind: "NATIVE",
        retained_base: "F",
        native_question: {
          clarification_id: "q1",
          text: "Which metal do you want?",
          category: "material_ambiguity",
          allowed_decisions: ["SELECT_OPTION", "SKIP", "UNKNOWN"],
          options: [{ value: "gold", option_id: "option-gold", label: "Gold" }],
        },
      },
    ];
    f.view();
    await screen.findByRole("option", { name: "Gold" });
    expect(
      screen.queryByRole("button", { name: "Accept offered change" }),
    ).not.toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByLabelText("Parameter / decision"),
      "option-gold",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() => expect(f.commands).toHaveLength(1));
    expect(f.commands[0]).toMatchObject({
      route: "clarification-answers",
      body: {
        schema_version: "2.0.0",
        plan_content_hash: frame.plan_hash,
        clarification_id: "q1",
        decision: "SELECT_OPTION",
        selected_option: "gold",
        selected_option_id: "option-gold",
      },
    });
  });

  it("presents a focused active question and expandable server-authorized choices", async () => {
    const f = fixture(true);
    const question = (id: string, value: string) => ({
      question_kind: "NATIVE" as const,
      retained_base: "F" as const,
      native_question: {
        clarification_id: id,
        text: id === "q1" ? "Which shape?" : "Which metal?",
        category: "material_ambiguity",
        allowed_decisions: ["SELECT_OPTION", "SKIP", "UNKNOWN"] as Array<
          "SELECT_OPTION" | "SKIP" | "UNKNOWN"
        >,
        options: [{ value, option_id: "option-" + value, label: value }],
      },
    });
    f.data.state!.questions = [
      question("q1", "oval"),
      question("q2", "gold"),
    ] as EnrichmentState["questions"];
    f.view();
    expect(await screen.findByText("Which shape?")).toBeInTheDocument();
    const other = screen.getByText("Other questions (1)").closest("details")!;
    expect(other.open).toBe(false);
    expect(screen.getByLabelText("Your message")).toBeInTheDocument();
    expect(screen.getByLabelText("Current design text")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Other questions (1)"));
    expect(other.open).toBe(true);
    expect(screen.getByText("Which metal?")).toBeInTheDocument();
    await userEvent.selectOptions(
      within(other).getByLabelText("Parameter / decision"),
      "option-gold",
    );
    await userEvent.click(
      within(other).getByRole("button", { name: "Save answer" }),
    );
    await waitFor(() => expect(f.commands).toHaveLength(1));
    expect(f.commands[0]).toMatchObject({
      route: "clarification-answers",
      body: { decision: "SELECT_OPTION", selected_option_id: "option-gold" },
    });
  });
  it("offers both parameter entry and free text for every native clarification", async () => {
    const f = fixture(true);
    f.data.state!.questions = [
      {
        question_kind: "NATIVE",
        retained_base: "F",
        native_question: {
          clarification_id: "metal-q",
          text: "Which metal?",
          category: "material_ambiguity",
          allowed_decisions: ["SELECT_OPTION", "SKIP", "UNKNOWN"],
          options: [{ value: "gold", label: "Gold", option_id: "gold-id" }],
        },
      },
    ];
    f.view();
    await screen.findByText("Which metal?");
    expect(screen.getByLabelText("Parameter / decision")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Parameter value in your words"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Clarification free-text answer"),
    ).toBeInTheDocument();
    await userEvent.selectOptions(
      screen.getByLabelText("Parameter / decision"),
      "gold-id",
    );
    await userEvent.type(
      screen.getByLabelText("Clarification free-text answer"),
      "Matte finish",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() =>
      expect(f.commands.some((c) => c.route === "clarification-answers")).toBe(
        true,
      ),
    );
    expect(f.commands.some((c) => c.route === "corrections")).toBe(true);
  });
  it("hides internal JSON and explains blocked final output in plain language", async () => {
    const f = fixture(true);
    server.use(
      http.get(`${prefix}/final-output`, () =>
        HttpResponse.json(
          { error: "final_output_blocked", detail: "Unresolved question" },
          { status: 409 },
        ),
      ),
    );
    f.view();
    expect(
      await screen.findByText(/A few design details still need your input/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/final_output_blocked/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("Why these design details?"));
    expect(
      screen.getByText(/These values come from your conversation/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/"revision_sha256"/)).not.toBeInTheDocument();
  });
  it("fails closed on unavailable/unauthorized conversation access", async () => {
    const f = fixture(true);
    server.use(
      http.get(`${prefix}/conversation`, () =>
        HttpResponse.json(
          { error: "not_found", detail: "Session not found" },
          { status: 404 },
        ),
      ),
    );
    f.view();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to open",
    );
    expect(screen.queryByLabelText("Your message")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "Open existing visualization workspace",
      }),
    ).toBeInTheDocument();
    expect(f.commands).toHaveLength(0);
  });
  it("does not show session content or entry actions when the session itself is outside scope", async () => {
    const f = fixture(true);
    server.use(
      http.get(`${root}/sessions/session`, () =>
        HttpResponse.json(
          { error: "not_found", detail: "Session not found" },
          { status: 404 },
        ),
      ),
    );
    f.view();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to open",
    );
    expect(screen.queryByLabelText("Your message")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", {
        name: "Open existing visualization workspace",
      }),
    ).not.toBeInTheDocument();
    expect(f.commands).toHaveLength(0);
  });
  it("wires admitted correction, explicit admission, typed KEEP consent and resume without changing server frames", async () => {
    const f = fixture(true);
    const c = new EnrichmentClient(f.api, "org", "session");
    const s = f.data.state!;
    await c.admit(s);
    expect(f.commands.at(-1)).toMatchObject({
      route: "continuation-admissions",
      body: { schema_version: "1.0.0", expected_head: frame },
    });
    s.extension_profile = "jewelai.prompt-enrichment.f05/1.0.0";
    await c.send(
      {
        session_id: "session",
        project_id: "project",
        role_id: "retail_client",
        locale: "en",
        created_at: "2026-11-05T00:00:00Z",
        updated_at: "2026-11-05T00:00:00Z",
        current_revision_id: "r1",
        artifacts: { questions: "2.0.0" },
      },
      f.data,
      "A new delta.",
    );
    expect(f.commands.at(-1)).toMatchObject({
      route: "corrections",
      body: { schema_version: "3.0.0", expected_head: frame },
    });
    await c.answer(
      s,
      {
        question_kind: "KEEP_RELEASE",
        offer: {
          offer_id: "offer1",
          intent_id: "intent1",
          requested_value_sha256: "valuehash",
          allowed_decisions: ["ACCEPT", "REJECT"],
          rendered_question: "Change the protected shape?",
        },
      },
      "ACCEPT",
    );
    expect(f.commands.at(-1)).toMatchObject({
      body: {
        schema_version: "3.0.0",
        answer_kind: "KEEP_RELEASE",
        intent_id: "intent1",
        requested_value_sha256: "valuehash",
        expected_head: frame,
      },
    });
    server.use(
      http.post(`${prefix}/clarifications/:id/resume`, async ({ request }) => {
        expect(await request.json()).toMatchObject({
          schema_version: "3.0.0",
          resume_kind: "KEEP_RELEASE",
          intent_id: "intent1",
          expected_head: frame,
        });
        return HttpResponse.json({});
      }),
    );
    await c.resume(s, "intent1", true);
  });
});
