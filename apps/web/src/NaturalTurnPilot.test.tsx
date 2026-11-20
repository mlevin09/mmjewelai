import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NaturalTurnPilot } from "./NaturalTurnPilot";
import type {
  Conversation,
  EnrichmentClient,
  NaturalTurnOptions,
  NaturalTurnRead,
} from "./enrichment";
import type { Session } from "./types";

afterEach(cleanup);

const options: NaturalTurnOptions = {
  schema_version: "2.0.0",
  model_configured: true,
  locale: "en",
  options: [{ value: "ring", label: "Ring", mapping_id: "map-1" }],
};
const base: NaturalTurnRead = {
  schema_version: "2.0.0",
  commit_status: "committed",
  delivery_status: "delivered",
  evidence: {
    message_id: "message-1",
    request: {
      turn_id: "turn-1",
      expected_revision_id: "revision-1",
      original_text: "I want a gold ring",
    },
  },
  input_hash: "hash",
  delivered_reply: {
    origin: "model",
    text: "Saved a ring. Gold was not yet confirmed.",
  },
  current_revision: { revision_id: "revision-2" },
  current_brief: "Gold ring — draft design.",
  is_current_revision: true,
};
const session = { locale: "en", project_id: "project" } as Session;
const snapshot = { revision: { revision_id: "revision-1" } } as Conversation;

function mount(
  saved: NaturalTurnRead | null,
  startNaturalTurn = vi.fn().mockResolvedValue(base),
) {
  const client = {
    organizationId: "org",
    startNaturalTurn,
    naturalTurn: vi.fn().mockResolvedValue(base),
  } as unknown as EnrichmentClient;
  const onViewCurrent = vi.fn().mockResolvedValue(undefined);
  render(
    <MemoryRouter>
      <NaturalTurnPilot
        client={client}
        session={session}
        snapshot={snapshot}
        saved={saved}
        options={options}
        onClose={vi.fn()}
        onViewCurrent={onViewCurrent}
      />
    </MemoryRouter>,
  );
  return { onViewCurrent, startNaturalTurn };
}

describe("US-01 schema2 Studio", () => {

  it.each([
    ["en", "Voice input"],
    ["ru", "Голосовой ввод"],
  ] as const)("restores existing microphone entry to the first-turn composer (%s)", (locale, buttonLabel) => {
    const localizedSession = { ...session, locale };
    const client = {
      api: {} as EnrichmentClient["api"],
      organizationId: "org",
      sessionId: "session",
      naturalTurn: vi.fn().mockResolvedValue(base),
      startNaturalTurn: vi.fn().mockResolvedValue(base),
    } as unknown as EnrichmentClient;
    render(
      <MemoryRouter>
        <NaturalTurnPilot
          client={client}
          session={localizedSession}
          snapshot={snapshot}
          saved={null}
          options={{ ...options, locale }}
          onClose={vi.fn()}
          onViewCurrent={vi.fn().mockResolvedValue(undefined)}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: buttonLabel })).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("sends raw text and a qualified typed selection through one atomic schema2 call", async () => {
    const { startNaturalTurn } = mount(null);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  I want a gold ring\n" },
    });
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "ring" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Submit original request" }),
    );
    await screen.findByText("Saved model reply");
    const call = startNaturalTurn.mock.calls[0];
    expect(call?.[0]).toBe(snapshot);
    expect(call?.[1]).toBe("  I want a gold ring\n");
    expect(call?.[2]).toMatch(/^[0-9a-f-]{36}$/);
    expect(call?.[3]).toBe("ring");
    expect(startNaturalTurn).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Gold ring — draft design.")).toBeInTheDocument();
  });

  it("labels fallback truthfully and never treats it as a model reply", () => {
    mount({
      ...base,
      delivered_reply: {
        origin: "fallback",
        text: "Saved only verified facts.",
      },
    });
    expect(screen.getByText("Saved fallback reply")).toBeInTheDocument();
    expect(screen.queryByText("Saved model reply")).not.toBeInTheDocument();
    expect(screen.getByText("Saved only verified facts.")).toBeInTheDocument();
  });

  it("shows committed pending State but does not invent a delivered reply", () => {
    mount({ ...base, delivery_status: "pending", delivered_reply: null });
    expect(
      screen.getByText(/Your input and State were committed/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Saved model reply")).not.toBeInTheDocument();
  });

  it("keeps an unverified local draft on read failure", async () => {
    const startNaturalTurn = vi
      .fn()
      .mockRejectedValue(new Error("read failed"));
    mount(null, startNaturalTurn);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "I want earrings" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Submit original request" }),
    );
    await screen.findByRole("alert");
    expect(
      screen.getByRole("region", { name: "Unverified local draft" }),
    ).toHaveTextContent("I want earrings");
    expect(screen.queryByText("Saved design brief")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Retry same turn/ }));
    await waitFor(() => expect(startNaturalTurn).toHaveBeenCalledTimes(2));
    expect(startNaturalTurn.mock.calls[0]?.[2]).toEqual(
      startNaturalTurn.mock.calls[1]?.[2],
    );
  });

  it("retries pending delivery with persisted turn id and original expected revision", async () => {
    const pending: NaturalTurnRead = {
      ...base,
      delivery_status: "pending",
      delivered_reply: null,
    };
    const { startNaturalTurn } = mount(pending);
    fireEvent.click(screen.getByRole("button", { name: /Retry same turn/ }));
    await waitFor(() => expect(startNaturalTurn).toHaveBeenCalledTimes(1));
    expect(startNaturalTurn).toHaveBeenCalledWith(
      snapshot,
      "I want a gold ring",
      "turn-1",
      undefined,
      "revision-1",
    );
  });

  it("marks historical State and permits current-state navigation", async () => {
    const { onViewCurrent } = mount({ ...base, is_current_revision: false });
    expect(screen.getByText(/Historical turn/)).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "View current design and history" }),
    );
    await waitFor(() => expect(onViewCurrent).toHaveBeenCalledOnce());
  });
});
