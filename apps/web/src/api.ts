export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type AccessTokenReader = () => Promise<string | null>;
type UnauthorizedHandler = () => Promise<void>;

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly readAccessToken: AccessTokenReader,
    private readonly onUnauthorized: UnauthorizedHandler,
  ) {}

  async request<T>(
    path: string,
    options: RequestInit & { organizationId?: string } = {},
  ): Promise<T> {
    const token = await this.readAccessToken();
    if (!token) {
      await this.onUnauthorized();
      throw new ApiError(401, "authentication_required", "Sign in is required");
    }
    const headers = new Headers(options.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (options.organizationId)
      headers.set("X-Organization-ID", options.organizationId);
    if (options.body && !(options.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(new URL(path, this.baseUrl), {
      ...options,
      headers,
    });
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null);
      const error = isErrorPayload(payload)
        ? payload
        : {
            error: "request_failed",
            detail: `Request failed (${response.status})`,
          };
      if (response.status === 401) await this.onUnauthorized();
      throw new ApiError(response.status, error.error, error.detail);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
}

function isErrorPayload(
  value: unknown,
): value is { error: string; detail: string } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.error === "string" && typeof candidate.detail === "string"
  );
}
