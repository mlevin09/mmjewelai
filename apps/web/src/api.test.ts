import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { ApiClient } from "./api";
import { server } from "./test/server";

const base = "https://api.example.test/";

describe("ApiClient", () => {
  it("uses the access token and organization header without putting tokens in URLs", async () => {
    server.use(
      http.get(`${base}sessions/one`, ({ request }) => {
        expect(request.url).toBe(`${base}sessions/one`);
        expect(request.headers.get("authorization")).toBe(
          "Bearer access-token",
        );
        expect(request.headers.get("x-organization-id")).toBe("org-one");
        return HttpResponse.json({ ok: true });
      }),
    );
    const client = new ApiClient(base, async () => "access-token", vi.fn());
    await expect(
      client.request<{ ok: boolean }>("/sessions/one", {
        organizationId: "org-one",
      }),
    ).resolves.toEqual({ ok: true });
  });

  it("lets the browser set multipart content type", async () => {
    const fetchMock = vi.fn(async (_url: URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).has("content-type")).toBe(false);
      expect(init?.body).toBeInstanceOf(FormData);
      return new Response(JSON.stringify({ asset_id: "asset-one" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const form = new FormData();
    form.set("file", new File(["png"], "reference.png", { type: "image/png" }));
    const client = new ApiClient(base, async () => "access-token", vi.fn());
    await client.request("/sessions/one/assets", {
      method: "POST",
      body: form,
    });
    vi.unstubAllGlobals();
  });

  it("clears authentication only for 401", async () => {
    const unauthorized = vi.fn(async () => undefined);
    const client = new ApiClient(
      base,
      async () => "access-token",
      unauthorized,
    );
    server.use(
      http.get(`${base}unauthorized`, () =>
        HttpResponse.json(
          { error: "authentication_failed", detail: "expired" },
          { status: 401 },
        ),
      ),
      http.get(`${base}forbidden`, () =>
        HttpResponse.json(
          { error: "authorization_denied", detail: "denied" },
          { status: 403 },
        ),
      ),
    );
    await expect(client.request("/unauthorized")).rejects.toMatchObject({
      status: 401,
    });
    expect(unauthorized).toHaveBeenCalledTimes(1);
    await expect(client.request("/forbidden")).rejects.toMatchObject({
      status: 403,
    });
    expect(unauthorized).toHaveBeenCalledTimes(1);
  });

  it("requires a token before issuing a request", async () => {
    const unauthorized = vi.fn(async () => undefined);
    const client = new ApiClient(base, async () => null, unauthorized);
    await expect(client.request("/me")).rejects.toMatchObject({
      status: 401,
      code: "authentication_required",
    });
    expect(unauthorized).toHaveBeenCalledOnce();
  });

  it("sends bounded prompt, generation, retry, and signed-access payloads", async () => {
    const seen: unknown[] = [];
    server.use(
      http.post(
        `${base}sessions/session-one/prompt-revisions`,
        async ({ request }) => {
          seen.push(await request.json());
          return HttpResponse.json(
            { prompt_revision_id: "prompt-one" },
            { status: 201 },
          );
        },
      ),
      http.post(
        `${base}sessions/session-one/generation-runs`,
        async ({ request }) => {
          seen.push(await request.json());
          return HttpResponse.json(
            { generation_run_id: "run-one" },
            { status: 201 },
          );
        },
      ),
      http.post(
        `${base}sessions/session-one/generation-runs/run-one/retry`,
        async ({ request }) => {
          seen.push(await request.json());
          return HttpResponse.json(
            { generation_run_id: "run-two" },
            { status: 201 },
          );
        },
      ),
      http.post(
        `${base}sessions/session-one/assets/asset-one/access`,
        async ({ request }) => {
          seen.push(await request.json());
          return HttpResponse.json({
            url: "https://asset.example.test/signed",
          });
        },
      ),
    );
    const client = new ApiClient(base, async () => "access-token", vi.fn());
    const post = (path: string, body: object) =>
      client.request(path, {
        organizationId: "org-one",
        method: "POST",
        body: JSON.stringify(body),
      });
    await post("/sessions/session-one/prompt-revisions", {
      expected_revision_id: "revision-one",
    });
    await post("/sessions/session-one/generation-runs", {
      prompt_revision_id: "prompt-one",
      profile_id: "production",
    });
    await post("/sessions/session-one/generation-runs/run-one/retry", {});
    await post("/sessions/session-one/assets/asset-one/access", {
      ttl_seconds: 300,
    });
    expect(seen).toEqual([
      { expected_revision_id: "revision-one" },
      { prompt_revision_id: "prompt-one", profile_id: "production" },
      {},
      { ttl_seconds: 300 },
    ]);
  });
});
