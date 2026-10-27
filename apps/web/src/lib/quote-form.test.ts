import { describe, expect, test } from "vitest";

import { formatMoney } from "./money";
import { parseQuoteEdit } from "./quote-form";

function form(fields: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(fields)) {
    for (const v of Array.isArray(value) ? value : [value]) data.append(name, v);
  }
  return data;
}

const base = {
  due_date: "2026-10-30",
  notes: " Matte ",
  line_ids: ["7"],
  line_7_part_name: "Phone stand",
  line_7_quantity: "20",
  line_7_material_code: "PETG-BLACK",
  line_7_grams_per_part: "35",
  line_7_minutes_per_part: "90",
  line_7_post_processing: ["sanding"],
};

describe("parseQuoteEdit", () => {
  test("reads the review form into the engine's edit shape", () => {
    expect(parseQuoteEdit(form({ ...base, rush: "on" }))).toEqual({
      ok: true,
      value: {
        due_date: "2026-10-30",
        rush: true,
        notes: "Matte",
        lines: [
          {
            part_name: "Phone stand",
            quantity: 20,
            material_code: "PETG-BLACK",
            grams_per_part: 35,
            minutes_per_part: 90,
            part_mm: null,
            post_processing: ["sanding"],
          },
        ],
      },
    });
  });

  test("a part size is all three numbers or none", () => {
    const sized = parseQuoteEdit(form({ ...base, line_7_part_x: "40", line_7_part_y: "30", line_7_part_z: "15" }));
    expect(sized.ok && sized.value.lines[0]?.part_mm).toEqual([40, 30, 15]);
    const partial = parseQuoteEdit(form({ ...base, line_7_part_x: "40" }));
    expect(partial.ok === false && partial.errors).toEqual(["Give all three part sizes, or none"]);
  });

  test("empty fields mean not known yet, never zero", () => {
    const result = parseQuoteEdit(
      form({ ...base, due_date: "", line_7_quantity: "", line_7_material_code: "", line_7_grams_per_part: "" }),
    );
    expect(result.ok && result.value.due_date).toBeNull();
    expect(result.ok && result.value.lines[0]).toMatchObject({
      quantity: null,
      material_code: null,
      grams_per_part: null,
    });
  });

  test("keeps rows in the order they appear on screen", () => {
    const result = parseQuoteEdit(
      form({ ...base, line_ids: ["7", "2"], line_2_part_name: "Lid", line_2_quantity: "1" }),
    );
    expect(result.ok && result.value.lines.map((l) => l.part_name)).toEqual(["Phone stand", "Lid"]);
  });

  test.each([
    ["line_7_quantity", "0", "Quantity must be a whole number from 1 to 10,000"],
    ["line_7_grams_per_part", "2.5", "Grams per part must be a whole number from 1 to 100,000"],
    ["line_7_part_name", " ", "Every line needs a part name"],
    ["due_date", "Friday", "Enter a valid due date"],
  ])("%s = %j is rejected", (field, value, message) => {
    expect(parseQuoteEdit(form({ ...base, [field]: value }))).toEqual({ ok: false, errors: [message] });
  });

  test("a form with no lines is rejected", () => {
    expect(parseQuoteEdit(form({ ...base, line_ids: [] }))).toEqual({
      ok: false,
      errors: ["Keep at least one line"],
    });
  });
});

test("formatMoney shows cents as currency", () => {
  expect(formatMoney(15100, "EUR")).toBe("€151.00");
  expect(formatMoney(5, "EUR")).toBe("€0.05");
});
