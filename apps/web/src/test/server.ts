import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

export const server = setupServer(
  // Existing deployments/sessions have no ST-01 receipt. Individual tests override this.
  http.get("*/v1/sessions/:sessionId/prompt-enrichment/first-turn", () =>
    HttpResponse.json(
      { error: "not_found", detail: "No first-turn receipt" },
      { status: 404 },
    ),
  ),
);
