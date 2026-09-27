import { QueryClient } from "@tanstack/react-query";
import { expect, it } from "vitest";

import { clearOrganizationQueries, keys } from "./queryKeys";

it("removes only the previous organization's tenant-scoped cache", () => {
  const client = new QueryClient();
  client.setQueryData(keys.projects("org-a"), ["a"]);
  client.setQueryData(keys.projects("org-b"), ["b"]);
  client.setQueryData(keys.me, { principal_id: "me" });
  clearOrganizationQueries(client, "org-a");
  expect(client.getQueryData(keys.projects("org-a"))).toBeUndefined();
  expect(client.getQueryData(keys.projects("org-b"))).toEqual(["b"]);
  expect(client.getQueryData(keys.me)).toEqual({ principal_id: "me" });
});
