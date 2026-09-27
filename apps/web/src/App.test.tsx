import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App, ReadyActions } from "./App";
import { ApiClient } from "./api";
import { AuthProvider } from "./auth";
import { server } from "./test/server";
import type { GenerationRun } from "./types";

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

describe("generation submission", () => {
  it("keeps generation creation single-flight until the active run is terminal", async () => {
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
        "http://localhost:8000/sessions/session-one/generation-runs",
        async () => {
          generationPosts += 1;
          await generationResponse;
          return HttpResponse.json({
            generation_run_id: `run-${generationPosts}`,
            prompt_revision_id: "prompt-one",
            profile_id: "standard",
            status: "pending",
            attempt: 1,
            parent_generation_run_id: null,
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
      const [activeRun, setActiveRun] = useState<GenerationRun | null>(null);
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
            activeRun={activeRun}
            onRun={setActiveRun}
          />
          <button
            onClick={() =>
              setActiveRun((run) =>
                run
                  ? {
                      ...run,
                      status:
                        run.status === "pending" ? "running" : "succeeded",
                    }
                  : null,
              )
            }
          >
            Advance active run
          </button>
        </>
      );
    }

    render(<Harness />);
    await userEvent.click(
      screen.getByRole("button", { name: "Create generation prompt" }),
    );
    const queue = await screen.findByRole("button", {
      name: "Queue generation",
    });
    fireEvent.click(queue);
    fireEvent.click(queue);
    fireEvent.click(queue);
    await waitFor(() => expect(generationPosts).toBe(1));
    expect(
      screen.getByRole("button", { name: "Queueing generation…" }),
    ).toBeDisabled();

    releaseGeneration();
    expect(
      await screen.findByText("Generation status: PENDING"),
    ).toBeInTheDocument();
    const pendingButton = screen.getByRole("button", {
      name: "Queue generation",
    });
    expect(pendingButton).toBeDisabled();
    fireEvent.click(pendingButton);
    expect(generationPosts).toBe(1);

    await userEvent.click(
      screen.getByRole("button", { name: "Advance active run" }),
    );
    expect(
      await screen.findByText("Generation status: RUNNING"),
    ).toBeInTheDocument();
    expect(pendingButton).toBeDisabled();
    fireEvent.click(pendingButton);
    expect(generationPosts).toBe(1);

    await userEvent.click(
      screen.getByRole("button", { name: "Advance active run" }),
    );
    await waitFor(() => expect(pendingButton).toBeEnabled());
    await userEvent.click(pendingButton);
    await waitFor(() => expect(generationPosts).toBe(2));
  });
});
