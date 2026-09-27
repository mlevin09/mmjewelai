import { afterEach, describe, expect, it, vi } from "vitest";

import { loadWebRuntimeConfig } from "./config";

const production = {
  apiBaseUrl: "https://api.example.test/",
  oidcAuthority: "https://identity.example.test",
  oidcClientId: "jewelai-web",
  oidcRedirectUri: "https://app.example.test/auth/callback",
  oidcPostLogoutRedirectUri: "https://app.example.test/login",
  oidcScope: "openid profile email",
  oidcAudience: "https://api.example.test",
};

afterEach(() => vi.unstubAllEnvs());

describe("production runtime config", () => {
  it("wins over development Vite values and preserves the audience", () => {
    const config = loadWebRuntimeConfig(production, {
      VITE_API_BASE_URL: "http://localhost:8000",
    } as ImportMetaEnv);
    expect(config).toEqual(production);
    expect(config.oidcAudience).toBe("https://api.example.test");
  });

  it.each([
    [{ ...production, apiBaseUrl: "http://api.example.test" }],
    [{ ...production, oidcAuthority: "not-a-url" }],
    [{ ...production, oidcScope: "profile email" }],
    [{ ...production, oidcAudience: "" }],
    [{ ...production, clientSecret: "forbidden" }],
  ])(
    "fails clearly for malformed or secret-bearing runtime config",
    (config) => {
      expect(() => loadWebRuntimeConfig(config, {} as ImportMetaEnv)).toThrow(
        "JewelAI runtime config",
      );
    },
  );
});
