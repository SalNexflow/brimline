import { describe, expect, test } from "vitest";

import { parseOrderForm } from "./order-form";

function form(fields: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(fields)) {
    for (const v of Array.isArray(value) ? value : [value]) data.append(name, v);
  }
  return data;
}

const valid = {
  customer_code: "C-HARBOR",
  due_date: "2026-11-06",
  notes: "  Matte finish.  ",
  line_part_name: ["Phone stand", ""],
  line_quantity: ["20", ""],
  line_material_code: ["PETG-BLACK", "PLA-BLACK"],
};

describe("parseOrderForm", () => {
  test("turns form fields into the engine's order shape", () => {
    expect(parseOrderForm(form({ ...valid, rush: "on" }))).toEqual({
      ok: true,
      value: {
        customer_code: "C-HARBOR",
        due_date: "2026-11-06",
        rush: true,
        notes: "Matte finish.",
        // The blank second row is dropped, and quantity becomes a number.
        lines: [{ part_name: "Phone stand", quantity: 20, material_code: "PETG-BLACK" }],
      },
    });
  });

  test("an unchecked rush box means not rush", () => {
    const result = parseOrderForm(form(valid));
    expect(result.ok && result.value.rush).toBe(false);
  });

  test("reports every problem in plain words", () => {
    const result = parseOrderForm(
      form({
        customer_code: "",
        due_date: "",
        notes: "",
        line_part_name: [""],
        line_quantity: ["0"],
        line_material_code: [""],
      }),
    );
    expect(result).toEqual({
      ok: false,
      errors: [
        "Choose a customer",
        "Enter a due date",
        "Every line needs a part name",
        "Quantity must be at least 1",
        "Every line needs a material",
      ],
    });
  });

  test("a form with no lines asks for one", () => {
    const result = parseOrderForm(
      form({ ...valid, line_part_name: [""], line_quantity: [""], line_material_code: [""] }),
    );
    expect(result).toEqual({ ok: false, errors: ["Add at least one line"] });
  });

  test.each([
    ["2.5", "Quantity must be a whole number"],
    ["many", "Quantity must be a number"],
    ["10001", "Quantity can be at most 10,000"],
  ])("quantity %s is rejected: %s", (quantity, message) => {
    const result = parseOrderForm(form({ ...valid, line_quantity: [quantity, ""] }));
    expect(result).toEqual({ ok: false, errors: [message] });
  });
});
