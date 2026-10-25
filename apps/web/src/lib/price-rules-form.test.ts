import { expect, test } from "vitest";

import { parsePriceRules } from "./price-rules-form";

function form(fields: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(fields)) {
    for (const v of Array.isArray(value) ? value : [value]) data.append(name, v);
  }
  return data;
}

const valid = {
  effective_from: "2026-11-01",
  setup_cents: "1800",
  rush_multiplier_percent: "160",
  material_codes: ["PLA-BLACK", "PETG-BLACK"],
  "material_PLA-BLACK": "3",
  "material_PETG-BLACK": "5",
  machine_fdm: "7",
  machine_resin: "10",
  machine_cnc: "50",
  post_sanding: "250",
  post_painting: "400",
  post_assembly: "600",
  note: " Winter ",
};

test("reads the form into the engine's shape", () => {
  expect(parsePriceRules(form(valid))).toEqual({
    ok: true,
    value: {
      effective_from: "2026-11-01",
      setup_cents: 1800,
      rush_multiplier_percent: 160,
      material_cents_per_gram: { "PLA-BLACK": 3, "PETG-BLACK": 5 },
      machine_cents_per_minute: { fdm: 7, resin: 10, cnc: 50 },
      post_process_cents_per_part: { sanding: 250, painting: 400, assembly: 600 },
      note: "Winter",
    },
  });
});

test.each([
  ["material_PETG-BLACK", "", "PETG-BLACK rate must be a whole number of cents from 0 to 10,000,000"],
  ["machine_cnc", "4.5", "CNC rate must be a whole number of cents from 0 to 10,000,000"],
  ["rush_multiplier_percent", "90", "Rush multiplier must be at least 100 %"],
  ["effective_from", "", "Enter the date the new prices start"],
])("%s = %j is rejected", (field, value, message) => {
  expect(parsePriceRules(form({ ...valid, [field]: value }))).toEqual({ ok: false, errors: [message] });
});

test("zero is a valid rate (free), an empty box is not", () => {
  const result = parsePriceRules(form({ ...valid, post_assembly: "0" }));
  expect(result.ok && result.value.post_process_cents_per_part.assembly).toBe(0);
});
