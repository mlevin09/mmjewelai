import { useState, type FormEvent } from "react";
import type { AnswerContract, DictionaryOption } from "./types";
import type { QuestionAnswer } from "./designUpdates";

export function AnswerForm({
  contract,
  options,
  onSubmit,
}: {
  contract: AnswerContract;
  options: DictionaryOption[];
  onSubmit: (answer: QuestionAnswer) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [width, setWidth] = useState("");
  const [depth, setDepth] = useState("");
  const [scope, setScope] = useState<"per_side" | "per_item" | "per_pair">(
    "per_item",
  );
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (contract.kind === "dictionary_id") {
      void onSubmit({ kind: "dictionary_id", value });
    } else if (contract.kind === "dimensions") {
      void onSubmit({
        kind: "dimensions",
        length: Number(value),
        width: Number(width),
        depth: Number(depth),
      });
    } else {
      void onSubmit({ kind: "stone_quantity", value: Number(value), scope });
    }
  };
  if (contract.kind === "dictionary_id") {
    return (
      <form onSubmit={submit} className="answer-form">
        <label>
          Select an answer
          <select
            required
            value={value}
            onChange={(event) => setValue(event.target.value)}
          >
            <option value="">Choose…</option>
            {options
              .filter((item) => item.category === contract.dictionary_category)
              .map((item) => (
                <option key={item.domain_id} value={item.domain_id}>
                  {item.term}
                </option>
              ))}
          </select>
        </label>
        <button type="submit">Save answer</button>
      </form>
    );
  }
  if (contract.kind === "dimensions") {
    return (
      <form onSubmit={submit} className="answer-form dimensions">
        <DimensionInput label="Length" value={value} setValue={setValue} />
        <DimensionInput label="Width" value={width} setValue={setWidth} />
        <DimensionInput label="Depth" value={depth} setValue={setDepth} />
        <button type="submit">Save dimensions</button>
      </form>
    );
  }
  return (
    <form onSubmit={submit} className="answer-form">
      <label>
        Quantity
        <input
          required
          min="1"
          step="1"
          type="number"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
      </label>
      <label>
        Scope
        <select
          value={scope}
          onChange={(event) => setScope(event.target.value as typeof scope)}
        >
          <option value="per_side">Per side</option>
          <option value="per_item">Per item</option>
          <option value="per_pair">Per pair</option>
        </select>
      </label>
      <button type="submit">Save quantity</button>
    </form>
  );
}

function DimensionInput({
  label,
  value,
  setValue,
}: {
  label: string;
  value: string;
  setValue: (value: string) => void;
}) {
  return (
    <label>
      {label} (mm)
      <input
        required
        min="0.01"
        step="0.01"
        type="number"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
    </label>
  );
}
