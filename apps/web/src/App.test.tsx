import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { AuthProvider } from "./auth";
import { server } from "./test/server";

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
