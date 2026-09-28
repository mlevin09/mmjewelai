import { afterEach, describe, expect, it, vi } from "vitest";

import { loadWebRuntimeConfig } from "./config";

const production = {
  apiBaseUrl: "https://api.example.test/",
  authProvider: "oidc" as const,
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
    expect(config.authProvider).toBe("oidc");
    if (config.authProvider !== "oidc") throw new Error("expected OIDC config");
    expect(config.oidcAudience).toBe("https://api.example.test");
  });

  it("accepts exact public Identity Platform client configuration", () => {
    const config = loadWebRuntimeConfig(
      {
        apiBaseUrl: "https://api.preprod.jewellai.online",
        authProvider: "identity_platform",
        identityPlatformApiKey: "public-browser-api-key",
        identityPlatformAuthDomain: "mmjewellai-preprod.firebaseapp.com",
        identityPlatformProjectId: "mmjewellai-preprod",
        identityPlatformAppId: "1:123:web:abc",
      },
      {} as ImportMetaEnv,
    );
    expect(config.authProvider).toBe("identity_platform");
    expect(config).not.toHaveProperty("clientSecret");
  });

  it.each([
    [{ ...production, apiBaseUrl: "http://api.example.test" }],
    [{ ...production, oidcAuthority: "not-a-url" }],
    [{ ...production, oidcScope: "profile email" }],
    [{ ...production, oidcAudience: "" }],
    [{ ...production, clientSecret: "forbidden" }],
    [
      {
        apiBaseUrl: "https://api.preprod.jewellai.online",
        authProvider: "identity_platform",
        identityPlatformApiKey: " public-key ",
        identityPlatformAuthDomain: "mmjewellai-preprod.firebaseapp.com",
        identityPlatformProjectId: "mmjewellai-preprod",
        identityPlatformAppId: "1:123:web:abc",
      },
    ],
  ])(
    "fails clearly for malformed or secret-bearing runtime config",
    (config) => {
      expect(() => loadWebRuntimeConfig(config, {} as ImportMetaEnv)).toThrow(
        "JewelAI runtime config",
      );
    },
  );
});
