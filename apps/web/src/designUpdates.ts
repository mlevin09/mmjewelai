import type { Design, MessageSource, ValueState } from "./types";

export type QuestionAnswer =
  | { kind: "dictionary_id"; value: string }
  | {
      kind: "dimensions";
      length: number;
      width: number;
      depth: number;
    }
  | {
      kind: "stone_quantity";
      value: number;
      scope: "per_side" | "per_item" | "per_pair";
    };

const dictionaryTargets = new Set([
  "center_stone.shape",
  "center_stone.setting",
  "metal.color",
]);

export function applyQuestionAnswer(
  design: Design,
  target: string,
  answer: QuestionAnswer,
  source: MessageSource,
): Design {
  const next = structuredClone(design);
  const state = explicitState(answerValue(answer), source);
  if (dictionaryTargets.has(target) && answer.kind === "dictionary_id") {
    if (target === "center_stone.shape") next.center_stone.shape = state;
    else if (target === "center_stone.setting")
      next.center_stone.setting = state;
    else next.metal.color = state;
    return next;
  }
  if (target === "center_stone.dimensions" && answer.kind === "dimensions") {
    next.center_stone.dimensions = state;
    return next;
  }
  const match = /^side_stones\[(\d+)]\.quantity$/.exec(target);
  if (match && answer.kind === "stone_quantity") {
    const indexText = match[1];
    if (indexText === undefined) throw new Error("Unsupported question target");
    const index = Number(indexText);
    const group = next.side_stones[index];
    if (!group)
      throw new Error("Side-stone target is outside the current design");
    group.quantity = state;
    return next;
  }
  const groupMatch = /^side_stones\.([a-z][a-z0-9_]{0,79})\.quantity$/.exec(
    target,
  );
  if (groupMatch && answer.kind === "stone_quantity") {
    const groupId = groupMatch[1];
    const group = next.side_stones.find((item) => item.group_id === groupId);
    if (!group)
      throw new Error("Side-stone target is outside the current design");
    group.quantity = state;
    return next;
  }
  throw new Error("Unsupported question target");
}

function answerValue(answer: QuestionAnswer): unknown {
  if (answer.kind === "dictionary_id") return answer.value;
  if (answer.kind === "dimensions") {
    for (const value of [answer.length, answer.width, answer.depth]) {
      if (!Number.isFinite(value) || value <= 0)
        throw new Error("Dimensions must be positive");
    }
    return {
      length: { value: answer.length, unit: "mm" },
      width: { value: answer.width, unit: "mm" },
      depth: { value: answer.depth, unit: "mm" },
    };
  }
  if (!Number.isInteger(answer.value) || answer.value <= 0) {
    throw new Error("Stone quantity must be a positive integer");
  }
  return { value: answer.value, scope: answer.scope };
}

function explicitState(
  value: unknown,
  source: MessageSource,
): ValueState<unknown> {
  return {
    availability: "value",
    origin: "explicit",
    value,
    source,
    confirmed: false,
    locked: false,
  };
}
