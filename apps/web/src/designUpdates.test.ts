import { describe, expect, it } from "vitest";

import { applyQuestionAnswer } from "./designUpdates";
import type { Design, MessageSource } from "./types";

const source: MessageSource = {
  kind: "message",
  message_id: "message-one",
  recorded_at: "2026-09-27T12:00:00Z",
};
const design: Design = {
  jewelry_type: null,
  metal: { material: null, color: null, purity: null, finish: null },
  center_stone: {
    material: null,
    shape: null,
    cut: null,
    weight: null,
    dimensions: null,
    color: null,
    setting: null,
    orientation: null,
  },
  side_stones: [{ group_id: "accent", stones: {}, quantity: null }],
  construction: {},
  style: null,
  references: null,
  visual_constraints: null,
};

describe("allowlisted design updates", () => {
  it.each([
    ["center_stone.shape", "oval", "center_stone"],
    ["center_stone.setting", "prong", "center_stone"],
    ["metal.color", "white", "metal"],
  ])("applies dictionary target %s", (target, value, area) => {
    const result = applyQuestionAnswer(
      design,
      target,
      { kind: "dictionary_id", value },
      source,
    );
    const container = result[area as "center_stone" | "metal"] as Record<
      string,
      unknown
    >;
    expect(JSON.stringify(container)).toContain(value);
    expect(result).not.toBe(design);
  });

  it("builds exact millimetre dimension objects", () => {
    const result = applyQuestionAnswer(
      design,
      "center_stone.dimensions",
      { kind: "dimensions", length: 8, width: 6, depth: 4 },
      source,
    );
    expect(result.center_stone.dimensions).toMatchObject({
      origin: "explicit",
      value: {
        length: { value: 8, unit: "mm" },
        width: { value: 6, unit: "mm" },
        depth: { value: 4, unit: "mm" },
      },
      source,
    });
  });

  it("updates only the bounded side-stone group", () => {
    const result = applyQuestionAnswer(
      design,
      "side_stones.accent.quantity",
      { kind: "stone_quantity", value: 3, scope: "per_side" },
      source,
    );
    expect(result.side_stones[0]?.quantity).toMatchObject({
      value: { value: 3, scope: "per_side" },
    });
  });

  it("also accepts an explicit bounded collection index", () => {
    const result = applyQuestionAnswer(
      design,
      "side_stones[0].quantity",
      { kind: "stone_quantity", value: 2, scope: "per_item" },
      source,
    );
    expect(result.side_stones[0]?.quantity).toMatchObject({
      value: { value: 2 },
    });
  });

  it("rejects unknown paths, mismatched answer kinds and invalid values", () => {
    expect(() =>
      applyQuestionAnswer(
        design,
        "metal.material",
        { kind: "dictionary_id", value: "gold" },
        source,
      ),
    ).toThrow("Unsupported question target");
    expect(() =>
      applyQuestionAnswer(
        design,
        "side_stones[2].quantity",
        { kind: "stone_quantity", value: 1, scope: "per_item" },
        source,
      ),
    ).toThrow("outside the current design");
    expect(() =>
      applyQuestionAnswer(
        design,
        "center_stone.dimensions",
        { kind: "dimensions", length: 0, width: 2, depth: 1 },
        source,
      ),
    ).toThrow("positive");
  });
});
