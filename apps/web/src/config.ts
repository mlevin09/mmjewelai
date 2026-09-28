interface BaseWebRuntimeConfig {
  apiBaseUrl: string;
}

export interface OidcWebRuntimeConfig extends BaseWebRuntimeConfig {
  authProvider: "oidc";
  oidcAuthority: string;
  oidcClientId: string;
  oidcRedirectUri: string;
  oidcPostLogoutRedirectUri: string;
  oidcScope: string;
  oidcAudience: string;
}

export interface IdentityPlatformWebRuntimeConfig extends BaseWebRuntimeConfig {
  authProvider: "identity_platform";
  identityPlatformApiKey: string;
  identityPlatformAuthDomain: string;
  identityPlatformProjectId: string;
  identityPlatformAppId: string;
}

export type WebRuntimeConfig =
  OidcWebRuntimeConfig | IdentityPlatformWebRuntimeConfig;

const commonKeys = ["apiBaseUrl", "authProvider"] as const;
const oidcKeys = [
  "oidcAuthority",
  "oidcClientId",
  "oidcRedirectUri",
  "oidcPostLogoutRedirectUri",
  "oidcScope",
  "oidcAudience",
] as const;
const identityPlatformKeys = [
  "identityPlatformApiKey",
  "identityPlatformAuthDomain",
  "identityPlatformProjectId",
  "identityPlatformAppId",
] as const;

export function loadWebRuntimeConfig(
  runtime: unknown = window.__JEWELAI_RUNTIME_CONFIG__,
  environment: ImportMetaEnv = import.meta.env,
): WebRuntimeConfig {
  const suppliedAtRuntime = runtime !== undefined;
  const selectedProvider = environment.VITE_AUTH_PROVIDER ?? "oidc";
  const candidate: unknown = suppliedAtRuntime
    ? runtime
    : selectedProvider === "identity_platform"
      ? {
          apiBaseUrl: environment.VITE_API_BASE_URL,
          authProvider: selectedProvider,
          identityPlatformApiKey: environment.VITE_IDENTITY_PLATFORM_API_KEY,
          identityPlatformAuthDomain:
            environment.VITE_IDENTITY_PLATFORM_AUTH_DOMAIN,
          identityPlatformProjectId:
            environment.VITE_IDENTITY_PLATFORM_PROJECT_ID,
          identityPlatformAppId: environment.VITE_IDENTITY_PLATFORM_APP_ID,
        }
      : {
          apiBaseUrl: environment.VITE_API_BASE_URL,
          authProvider: "oidc",
          oidcAuthority: environment.VITE_OIDC_AUTHORITY,
          oidcClientId: environment.VITE_OIDC_CLIENT_ID,
          oidcRedirectUri: environment.VITE_OIDC_REDIRECT_URI,
          oidcPostLogoutRedirectUri:
            environment.VITE_OIDC_POST_LOGOUT_REDIRECT_URI,
          oidcScope: environment.VITE_OIDC_SCOPE,
          oidcAudience: environment.VITE_OIDC_AUDIENCE,
        };
  if (!isRecord(candidate))
    throw new Error("JewelAI runtime config must be an object");
  const provider = candidate.authProvider ?? "oidc";
  if (provider !== "oidc" && provider !== "identity_platform") {
    throw new Error("JewelAI runtime config authProvider is unsupported");
  }
  const allowed = new Set<string>([
    ...commonKeys,
    ...(provider === "oidc" ? oidcKeys : identityPlatformKeys),
  ]);
  if (Object.keys(candidate).some((key) => !allowed.has(key))) {
    throw new Error("JewelAI runtime config contains unsupported fields");
  }
  const normalized = { ...candidate, authProvider: provider } as Record<
    string,
    unknown
  >;
  const required = [
    "apiBaseUrl",
    ...(provider === "oidc" ? oidcKeys : identityPlatformKeys),
  ];
  for (const key of required) {
    const value = normalized[key];
    if (typeof value !== "string" || value === "" || value !== value.trim()) {
      throw new Error(
        `JewelAI runtime config ${key} must be a non-empty exact string`,
      );
    }
  }
  requireUrl(normalized.apiBaseUrl as string, "apiBaseUrl", suppliedAtRuntime);
  if (provider === "oidc") {
    for (const key of [
      "oidcAuthority",
      "oidcRedirectUri",
      "oidcPostLogoutRedirectUri",
    ] as const) {
      requireUrl(normalized[key] as string, key, suppliedAtRuntime);
    }
    if (!(normalized.oidcScope as string).split(/\s+/).includes("openid")) {
      throw new Error("JewelAI runtime config oidcScope must contain openid");
    }
  } else if (
    !/^[a-z][a-z0-9-]{4,29}$/.test(
      normalized.identityPlatformProjectId as string,
    )
  ) {
    throw new Error(
      "JewelAI runtime config identityPlatformProjectId is invalid",
    );
  }
  return Object.freeze(normalized) as unknown as WebRuntimeConfig;
}

function requireUrl(value: string, name: string, requireHttps: boolean): void {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`JewelAI runtime config ${name} must be an absolute URL`);
  }
  if (
    url.username ||
    url.password ||
    (url.protocol === "http:" && requireHttps)
  ) {
    throw new Error(`JewelAI runtime config ${name} must be an HTTPS URL`);
  }
  if (!["https:", "http:"].includes(url.protocol)) {
    throw new Error(`JewelAI runtime config ${name} must be an HTTP(S) URL`);
  }
  if (
    url.protocol === "http:" &&
    !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  ) {
    throw new Error(
      `JewelAI runtime config ${name} permits HTTP only for local development`,
    );
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function getWebRuntimeConfig(): WebRuntimeConfig {
  return loadWebRuntimeConfig();
}
