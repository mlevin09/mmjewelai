export interface WebRuntimeConfig {
  apiBaseUrl: string;
  oidcAuthority: string;
  oidcClientId: string;
  oidcRedirectUri: string;
  oidcPostLogoutRedirectUri: string;
  oidcScope: string;
  oidcAudience: string;
}

const keys = [
  "apiBaseUrl",
  "oidcAuthority",
  "oidcClientId",
  "oidcRedirectUri",
  "oidcPostLogoutRedirectUri",
  "oidcScope",
  "oidcAudience",
] as const;

export function loadWebRuntimeConfig(
  runtime: unknown = window.__JEWELAI_RUNTIME_CONFIG__,
  environment: ImportMetaEnv = import.meta.env,
): WebRuntimeConfig {
  const suppliedAtRuntime = runtime !== undefined;
  const candidate: unknown = suppliedAtRuntime
    ? runtime
    : {
        apiBaseUrl: environment.VITE_API_BASE_URL,
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
  const unknown = Object.keys(candidate).filter(
    (key) => !keys.includes(key as (typeof keys)[number]),
  );
  if (unknown.length)
    throw new Error("JewelAI runtime config contains unsupported fields");
  for (const key of keys) {
    if (
      typeof candidate[key] !== "string" ||
      candidate[key] === "" ||
      candidate[key] !== candidate[key].trim()
    ) {
      throw new Error(
        `JewelAI runtime config ${key} must be a non-empty exact string`,
      );
    }
  }
  const config = candidate as unknown as WebRuntimeConfig;
  requireUrl(config.apiBaseUrl, "apiBaseUrl", suppliedAtRuntime);
  requireUrl(config.oidcAuthority, "oidcAuthority", suppliedAtRuntime);
  requireUrl(config.oidcRedirectUri, "oidcRedirectUri", suppliedAtRuntime);
  requireUrl(
    config.oidcPostLogoutRedirectUri,
    "oidcPostLogoutRedirectUri",
    suppliedAtRuntime,
  );
  if (!config.oidcScope.split(/\s+/).includes("openid")) {
    throw new Error("JewelAI runtime config oidcScope must contain openid");
  }
  return Object.freeze({ ...config });
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
