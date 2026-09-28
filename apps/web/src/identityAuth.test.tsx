import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

interface FirebaseMock {
  currentUser: { uid: string; getIdToken: () => Promise<string> } | null;
  setPersistence: ReturnType<typeof vi.fn>;
  signIn: ReturnType<typeof vi.fn>;
  signOut: ReturnType<typeof vi.fn>;
}

const firebase = vi.hoisted((): FirebaseMock => {
  const currentUser: { uid: string; getIdToken: () => Promise<string> } | null =
    {
      uid: "firebase-user-1",
      getIdToken: vi.fn(async () => "identity-platform-id-token"),
    };
  return {
    currentUser,
    setPersistence: vi.fn(async () => undefined),
    signIn: vi.fn(async () => undefined),
    signOut: vi.fn(async () => {
      firebase.currentUser = null;
    }),
  };
});

vi.mock("firebase/app", () => ({
  getApps: () => [],
  initializeApp: () => ({ name: "jewelai-identity-platform" }),
}));

vi.mock("firebase/auth", () => ({
  browserSessionPersistence: { type: "SESSION" },
  getAuth: () => ({
    get currentUser() {
      return firebase.currentUser;
    },
  }),
  onAuthStateChanged: (_auth: unknown, listener: (user: unknown) => void) => {
    listener(firebase.currentUser);
    return () => {};
  },
  setPersistence: firebase.setPersistence,
  signInWithEmailAndPassword: firebase.signIn,
  signOut: firebase.signOut,
}));

import { AuthProvider, useAuth } from "./auth";

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span>{auth.user ? "signed-in" : "signed-out"}</span>
      <button onClick={() => void auth.login("user@example.test", "password")}>
        login
      </button>
      <button onClick={() => void auth.logout()}>logout</button>
      <button onClick={() => void auth.accessToken().then((token) => token)}>
        token
      </button>
    </div>
  );
}

describe("Identity Platform browser authentication", () => {
  beforeEach(() => {
    firebase.currentUser = {
      uid: "firebase-user-1",
      getIdToken: vi.fn(async () => "identity-platform-id-token"),
    };
    vi.stubGlobal("__JEWELAI_RUNTIME_CONFIG__", undefined);
    Object.defineProperty(window, "__JEWELAI_RUNTIME_CONFIG__", {
      configurable: true,
      value: {
        apiBaseUrl: "https://api.preprod.jewellai.online",
        authProvider: "identity_platform",
        identityPlatformApiKey: "public-browser-key",
        identityPlatformAuthDomain: "mmjewellai-preprod.firebaseapp.com",
        identityPlatformProjectId: "mmjewellai-preprod",
        identityPlatformAppId: "1:123:web:abc",
      },
    });
    vi.clearAllMocks();
  });

  it("uses session persistence, observes auth state, signs in, and logs out", async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await screen.findByText("signed-in");
    expect(firebase.setPersistence).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "login" }));
    expect(firebase.signIn).toHaveBeenCalledWith(
      expect.anything(),
      "user@example.test",
      "password",
    );
    await userEvent.click(screen.getByRole("button", { name: "logout" }));
    await waitFor(() =>
      expect(screen.getByText("signed-out")).toBeInTheDocument(),
    );
    expect(firebase.signOut).toHaveBeenCalledOnce();
  });
});
