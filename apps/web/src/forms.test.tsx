import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerForm } from "./forms";

describe("AnswerForm", () => {
  it("renders only options in the requested dictionary category", () => {
    render(
      <AnswerForm
        contract={{
          kind: "dictionary_id",
          schema_type: "DomainId",
          dictionary_category: "stone_shape",
        }}
        options={[
          { domain_id: "oval", category: "stone_shape", term: "Oval" },
          { domain_id: "white", category: "metal_color", term: "White" },
        ]}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole("option", { name: "Oval" })).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "White" }),
    ).not.toBeInTheDocument();
  });

  it("submits positive dimensions", async () => {
    const submit = vi.fn(async () => undefined);
    render(
      <AnswerForm
        contract={{
          kind: "dimensions",
          unit: "mm",
          components: ["length", "width", "depth"],
        }}
        options={[]}
        onSubmit={submit}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Length (mm)"), "8");
    await user.type(screen.getByLabelText("Width (mm)"), "6");
    await user.type(screen.getByLabelText("Depth (mm)"), "4");
    await user.click(screen.getByRole("button", { name: "Save dimensions" }));
    expect(submit).toHaveBeenCalledWith({
      kind: "dimensions",
      length: 8,
      width: 6,
      depth: 4,
    });
  });

  it("submits quantity with scope", async () => {
    const submit = vi.fn(async () => undefined);
    render(
      <AnswerForm
        contract={{
          kind: "stone_quantity",
          value: "positive_integer",
          scopes: ["per_side", "per_item", "per_pair"],
        }}
        options={[]}
        onSubmit={submit}
      />,
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Quantity"), "4");
    await user.selectOptions(screen.getByLabelText("Scope"), "per_pair");
    await user.click(screen.getByRole("button", { name: "Save quantity" }));
    expect(submit).toHaveBeenCalledWith({
      kind: "stone_quantity",
      value: 4,
      scope: "per_pair",
    });
  });
});
