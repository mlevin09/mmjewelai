import type { QueryClient } from "@tanstack/react-query";

export const keys = {
  me: ["me"] as const,
  catalog: ["ui-catalog"] as const,
  projects: (organizationId: string) =>
    ["organization", organizationId, "projects"] as const,
  sessions: (organizationId: string, projectId: string) =>
    ["organization", organizationId, "project", projectId, "sessions"] as const,
  workspace: (organizationId: string, sessionId: string, resource: string) =>
    ["organization", organizationId, "session", sessionId, resource] as const,
};

export function clearOrganizationQueries(
  client: QueryClient,
  organizationId: string,
): void {
  client.removeQueries({
    predicate: (query) =>
      query.queryKey[0] === "organization" &&
      query.queryKey[1] === organizationId,
  });
}
