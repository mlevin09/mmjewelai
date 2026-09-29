import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App, ReadyActions, VisualizationIterationPanel } from "./App";
import { ApiClient } from "./api";
import { AuthProvider } from "./auth";
import { server } from "./test/server";
import type { VisualizationIteration } from "./types";

const oidc = vi.hoisted(() => ({
  currentUser: null as null | { access_token: string },
  signinRedirect: vi.fn(async () => undefined),
  signinRedirectCallback: vi.fn(async () => ({ access_token: "access-token" })),
  signoutRedirect: vi.fn(async () => undefined),
  removeUser: vi.fn(async () => undefined),
}));

vi.mock("oidc-client-ts", () => ({
  UserManager: class {
    getUser = vi.fn(async () => oidc.currentUser);
    signinRedirect = oidc.signinRedirect;
    signinRedirectCallback = oidc.signinRedirectCallback;
    signoutRedirect = oidc.signoutRedirect;
    removeUser = oidc.removeUser;
  },
  WebStorageStateStore: class {},
}));

function renderApp(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <QueryClientProvider client={client}>
          <App />
        </QueryClientProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  oidc.currentUser = null;
  vi.clearAllMocks();
  vi.stubEnv("VITE_API_BASE_URL", "http://localhost:8000/");
  vi.stubEnv("VITE_OIDC_AUTHORITY", "https://identity.example.test");
  vi.stubEnv("VITE_OIDC_CLIENT_ID", "jewelai-web");
  vi.stubEnv("VITE_OIDC_REDIRECT_URI", "http://localhost:5173/auth/callback");
  vi.stubEnv(
    "VITE_OIDC_POST_LOGOUT_REDIRECT_URI",
    "http://localhost:5173/login",
  );
  vi.stubEnv("VITE_OIDC_SCOPE", "openid profile email");
  vi.stubEnv("VITE_OIDC_AUDIENCE", "https://api.example.test");
});

describe("authentication shell", () => {
  it("starts a redirect login from the public login page", async () => {
    renderApp("/login");
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Sign in securely" }),
    );
    expect(oidc.signinRedirect).toHaveBeenCalledOnce();
  });

  it("renders the authenticated principal and logs out through OIDC", async () => {
    oidc.currentUser = { access_token: "access-token" };
    server.use(
      http.get("http://localhost:8000/me", ({ request }) => {
        expect(request.headers.get("authorization")).toBe(
          "Bearer access-token",
        );
        return HttpResponse.json({
          principal_id: "principal-one",
          email: "alice@example.test",
          display_name: "Alice",
          memberships: [],
        });
      }),
    );
    renderApp("/");
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(oidc.signoutRedirect).toHaveBeenCalledOnce());
  });
});

describe("parallel visualization submission", () => {
  it("keeps iteration creation single-flight until provider runs are terminal", async () => {
    let generationPosts = 0;
    let releaseGeneration!: () => void;
    const generationResponse = new Promise<void>((resolve) => {
      releaseGeneration = resolve;
    });
    server.use(
      http.post(
        "http://localhost:8000/sessions/session-one/prompt-revisions",
        () =>
          HttpResponse.json({
            prompt_revision_id: "prompt-one",
            specification_revision_id: "revision-one",
            compiled_prompt: { prompt_text: "A bounded prompt" },
            created_at: "2026-09-27T00:00:00Z",
          }),
      ),
      http.post(
        "http://localhost:8000/sessions/session-one/visualization-iterations",
        async () => {
          generationPosts += 1;
          await generationResponse;
          return HttpResponse.json({
            iteration_id: `iteration-${generationPosts}`,
            session_id: "session-one",
            prompt_revision_id: "prompt-one",
            prompt_content_hash: "a".repeat(64),
            status: "pending",
            runs: [],
            results: [],
            selection: null,
            current_visual_asset_id: null,
            created_at: "2026-09-27T00:00:00Z",
          });
        },
      ),
    );
    const api = new ApiClient(
      "http://localhost:8000/",
      async () => "access-token",
      async () => undefined,
    );

    function Harness() {
      const [activeIteration, setActiveIteration] =
        useState<VisualizationIteration | null>(null);
      return (
        <>
          <ReadyActions
            api={api}
            organizationId="organization-one"
            sessionId="session-one"
            revisionId="revision-one"
            profiles={[
              {
                profile_id: "standard",
                profile_version: "1.0.0",
                output_count: 1,
              },
            ]}
            activeIteration={activeIteration}
            onIteration={setActiveIteration}
          />
          <button
            onClick={() =>
              setActiveIteration((iteration) =>
                iteration
                  ? {
                      ...iteration,
                      status: "succeeded",
                    }
                  : null,
              )
            }
          >
            Complete iteration
          </button>
        </>
      );
    }

    render(<Harness />);
    await userEvent.click(
      screen.getByRole("button", { name: "Create generation prompt" }),
    );
    const queue = await screen.findByRole("button", {
      name: "Generate provider results",
    });
    fireEvent.click(queue);
    fireEvent.click(queue);
    fireEvent.click(queue);
    await waitFor(() => expect(generationPosts).toBe(1));
    expect(
      screen.getByRole("button", { name: "Queueing providers…" }),
    ).toBeDisabled();

    releaseGeneration();
    expect(
      await screen.findByText("Visualization iteration: PENDING"),
    ).toBeInTheDocument();
    const pendingButton = screen.getByRole("button", {
      name: "Generate provider results",
    });
    expect(pendingButton).toBeDisabled();
    fireEvent.click(pendingButton);
    expect(generationPosts).toBe(1);

    await userEvent.click(
      screen.getByRole("button", { name: "Complete iteration" }),
    );
    await waitFor(() => expect(pendingButton).toBeEnabled());
    await userEvent.click(pendingButton);
    await waitFor(() => expect(generationPosts).toBe(2));
  });
});

describe("visualization result selection", () => {
  it("shows grouped provider results and persists one selected Asset", async () => {
    const decisions: unknown[] = [];
    server.use(
      http.post(
        "http://localhost:8000/sessions/session-one/visualization-iterations/iteration-one/decision",
        async ({ request }) => {
          decisions.push(await request.json());
          return HttpResponse.json({});
        },
      ),
    );
    const api = new ApiClient(
      "http://localhost:8000/",
      async () => "access-token",
      async () => undefined,
    );
    const iteration: VisualizationIteration = {
      iteration_id: "iteration-one",
      session_id: "session-one",
      prompt_revision_id: "prompt-one",
      prompt_content_hash: "a".repeat(64),
      status: "succeeded",
      runs: [],
      results: [
        {
          generation_run_id: "run-google",
          provider: "google",
          model: "gemini-image",
          asset: {
            asset_id: "asset-google",
            kind: "generated",
            status: "ready",
            content_type: "image/png",
            byte_size: 100,
            generation_run_id: "run-google",
            created_at: "2026-09-27T00:00:00Z",
          },
        },
        {
          generation_run_id: "run-openai",
          provider: "openai",
          model: "gpt-image",
          asset: {
            asset_id: "asset-openai",
            kind: "generated",
            status: "ready",
            content_type: "image/png",
            byte_size: 100,
            generation_run_id: "run-openai",
            created_at: "2026-09-27T00:00:00Z",
          },
        },
      ],
      selection: null,
      current_visual_asset_id: null,
      created_at: "2026-09-27T00:00:00Z",
    };
    render(
      <VisualizationIterationPanel
        api={api}
        organizationId="organization-one"
        sessionId="session-one"
        locale="en"
        iterations={[iteration]}
        urls={{}}
        onView={vi.fn(async () => undefined)}
        onChanged={vi.fn(async () => undefined)}
      />,
    );

    expect(screen.getByText("google")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
    await userEvent.click(
      screen.getAllByRole("button", { name: "Select" })[0]!,
    );
    await waitFor(() =>
      expect(decisions).toEqual([
        { decision: "select", asset_id: "asset-google" },
      ]),
    );
  });
});

describe("text intake", () => {
  it("submits normal text once, refreshes the revision, and shows clarification", async () => {
    oidc.currentUser = { access_token: "access-token" };
    let currentRevision = "revision-one";
    let intakePosts = 0;
    let releaseIntake!: () => void;
    const intakeWait = new Promise<void>((resolve) => {
      releaseIntake = resolve;
    });
    const design = (shape: unknown = null) => ({
      jewelry_type: null,
      metal: { material: null, color: null, purity: null, finish: null },
      center_stone: {
        material: null,
        shape,
        cut: null,
        weight: null,
        dimensions: null,
        color: null,
        setting: null,
        orientation: null,
      },
      side_stones: [],
      construction: null,
      style: null,
      references: null,
      visual_constraints: null,
    });
    const revision = (id: string, shape: unknown = null) => ({
      schema_version: "1.0.0",
      design_id: "design-one",
      revision_id: id,
      revision: id === "revision-one" ? 1 : 2,
      parent_revision_id: id === "revision-one" ? null : "revision-one",
      created_at: "2026-09-29T00:00:00Z",
      event: {},
      design: design(shape),
    });
    server.use(
      http.get("http://localhost:8000/me", () =>
        HttpResponse.json({
          principal_id: "principal-one",
          email: "alice@example.test",
          display_name: "Alice",
          memberships: [
            {
              organization_id: "organization-one",
              organization_name: "JewelAI",
              role: "owner",
            },
          ],
        }),
      ),
      http.get("http://localhost:8000/ui/catalog", () =>
        HttpResponse.json({
          roles_artifact_version: "1.0.0",
          roles: [{ role_id: "retail_client" }],
          locales: ["en", "ru"],
          generation_profiles: [],
        }),
      ),
      http.get("http://localhost:8000/sessions/session-one", () =>
        HttpResponse.json({
          session_id: "session-one",
          project_id: "project-one",
          role_id: "retail_client",
          locale: "en",
          created_at: "2026-09-29T00:00:00Z",
          updated_at: "2026-09-29T00:00:00Z",
          current_revision_id: currentRevision,
          artifacts: {},
        }),
      ),
      http.get(
        "http://localhost:8000/sessions/session-one/revisions/:revisionId",
        ({ params }) =>
          HttpResponse.json(
            revision(
              String(params.revisionId),
              params.revisionId === "revision-two"
                ? {
                    availability: "value",
                    origin: "explicit",
                    value: "oval",
                    confirmed: false,
                    locked: false,
                  }
                : null,
            ),
          ),
      ),
      http.get(
        "http://localhost:8000/sessions/session-one/dictionary-options",
        () =>
          HttpResponse.json({
            artifact_version: "1.0.0",
            locale: "en",
            options: [],
          }),
      ),
      http.get("http://localhost:8000/sessions/session-one/assets", () =>
        HttpResponse.json({ assets: [] }),
      ),
      http.get(
        "http://localhost:8000/sessions/session-one/generation-runs",
        () => HttpResponse.json({ generation_runs: [] }),
      ),
      http.post(
        "http://localhost:8000/sessions/session-one/text-intake",
        async ({ request }) => {
          intakePosts += 1;
          const body = (await request.json()) as Record<string, unknown>;
          if (intakePosts === 2) {
            return HttpResponse.json(
              {
                error: "text_understanding_unavailable",
                detail: "Text understanding is temporarily unavailable",
              },
              { status: 503 },
            );
          }
          expect(body).toEqual({
            expected_revision_id: "revision-one",
            content: "I want an oval center stone.",
          });
          await intakeWait;
          currentRevision = "revision-two";
          return HttpResponse.json({
            message: {
              message_id: "message-one",
              content: body.content,
              created_at: "2026-09-29T00:00:00Z",
            },
            proposal: { has_changes: true, accepted_updates: [], issues: [] },
            revision: revision("revision-two"),
            evaluation: {
              revision_id: "revision-two",
              decision: {
                decision: "ask",
                reason: "A deterministic rule selected this question.",
                target: "center_stone.setting",
                concrete_target: "center_stone.setting",
                question_id: "CENTER_STONE_SETTING",
              },
              rendered_question: {
                question_id: "CENTER_STONE_SETTING",
                wording: "How should the center stone be set?",
                target: "center_stone.setting",
                answer_contract: {
                  kind: "dictionary_id",
                  dictionary_category: "stone_setting",
                  schema_type: "DomainId",
                },
                locale: "en",
              },
            },
          });
        },
      ),
    );

    renderApp("/organizations/organization-one/sessions/session-one");
    const input = await screen.findByLabelText("Jewelry description");
    await userEvent.type(input, "I want an oval center stone.");
    const submit = screen.getByRole("button", { name: "Understand request" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(
      await screen.findByRole("button", { name: "Understanding…" }),
    ).toBeDisabled();
    expect(intakePosts).toBe(1);
    releaseIntake();
    expect(
      await screen.findByText("How should the center stone be set?"),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Oval")).toBeInTheDocument());
    const refreshedInput = await screen.findByLabelText("Jewelry description");
    await userEvent.type(refreshedInput, "Try another request.");
    await userEvent.click(
      screen.getByRole("button", { name: "Understand request" }),
    );
    expect(
      await screen.findByText(
        "Text understanding is temporarily unavailable. Try again.",
      ),
    ).toBeInTheDocument();
  });
});
