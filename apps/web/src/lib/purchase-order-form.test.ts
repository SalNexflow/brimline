import { describe, expect, it } from "vitest";

import { parsePurchaseOrder } from "./purchase-order-form";

const NOW = new Date("2026-10-26T09:00:00Z");

function form(values: Record<string, string>): FormData {
  const f = new FormData();
  for (const [k, v] of Object.entries(values)) f.set(k, v);
  return f;
}

const OK = { material_code: "TPU-BLACK", grams: "500", supplier: "Quickspool Express", expected_at: "2026-10-29T10:00" };

describe("parsePurchaseOrder", () => {
  it("reads a good order and turns shop time into UTC", () => {
    // Thu 29 Oct 10:00 in Berlin is 09:00 UTC (winter time since 25 Oct).
    expect(parsePurchaseOrder(form(OK), "Europe/Berlin", NOW)).toEqual({
      ok: true,
      value: { material_code: "TPU-BLACK", grams: 500, supplier: "Quickspool Express", expected_at: "2026-10-29T09:00:00.000Z" },
    });
  });

  it.each([
    [{ grams: "0" }, "Grams"],
    [{ grams: "12.5" }, "Grams"],
    [{ grams: "1000001" }, "Grams"],
    [{ supplier: "" }, "supplier"],
    [{ material_code: "" }, "material"],
    [{ expected_at: "" }, "expected delivery"],
    [{ expected_at: "2026-10-20T10:00" }, "in the past"],
  ])("refuses %o", (change, message) => {
    const r = parsePurchaseOrder(form({ ...OK, ...change }), "Europe/Berlin", NOW);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.join(" ")).toContain(message);
  });
});
