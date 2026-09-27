import { WebStorageStateStore } from "oidc-client-ts";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createUserManager } from "./auth";

afterEach(() => vi.unstubAllEnvs());

describe("OIDC public-client configuration", () => {
  it("uses authorization code plus PKCE state in session storage", () => {
    vi.stubEnv("VITE_OIDC_AUTHORITY", "https://identity.example.test");
    vi.stubEnv("VITE_OIDC_CLIENT_ID", "jewelai-web");
    vi.stubEnv(
      "VITE_OIDC_REDIRECT_URI",
      "https://app.example.test/auth/callback",
    );
    vi.stubEnv(
      "VITE_OIDC_POST_LOGOUT_REDIRECT_URI",
      "https://app.example.test/login",
    );
    vi.stubEnv("VITE_OIDC_SCOPE", "openid profile email");
    const localWrite = vi.spyOn(window.localStorage, "setItem");
    const manager = createUserManager();
    expect(manager.settings.response_type).toBe("code");
    expect(manager.settings.client_secret).toBeUndefined();
    expect(manager.settings.userStore).toBeInstanceOf(WebStorageStateStore);
    expect(manager.settings.stateStore).toBeInstanceOf(WebStorageStateStore);
    expect(localWrite).not.toHaveBeenCalled();
  });
});
