import { describe, expect, it } from "vitest";

import { chipLabel, decodeFilter, encodeFilter, parseValue, type Filter } from "./search-filter";

describe("parseValue", () => {
  it("reads each kind of chip value", () => {
    expect(parseValue("material", "in", "PLA-BLACK, PETG-BLACK")).toEqual({ ok: true, value: ["PLA-BLACK", "PETG-BLACK"] });
    expect(parseValue("rush", "is", "false")).toEqual({ ok: true, value: false });
    expect(parseValue("quantity", "gte", "10")).toEqual({ ok: true, value: 10 });
    expect(parseValue("due_date", "between", "2026-10-26 to 2026-11-01")).toEqual({
      ok: true,
      value: ["2026-10-26", "2026-11-01"],
    });
    expect(parseValue("part_name", "contains", "  bracket ")).toEqual({ ok: true, value: "bracket" });
  });

  it("refuses what the engine would refuse", () => {
    expect(parseValue("quantity", "contains", "1")).toMatchObject({ ok: false });
    expect(parseValue("overdue", "is", "false")).toEqual({ ok: false, error: "Overdue can only be yes" });
    expect(parseValue("due_date", "on", "30/10")).toEqual({ ok: false, error: "A date is written YYYY-MM-DD" });
    expect(parseValue("quantity", "gt", "a few")).toEqual({ ok: false, error: "Quantity is a whole number" });
    expect(parseValue("customer", "in", " , ")).toMatchObject({ ok: false });
  });
});

describe("filters in the URL", () => {
  const f: Filter = {
    sort: "created",
    conditions: [
      { field: "part_name", op: "contains", value: "Zahnrad ü & '; DROP" },
      { field: "printed", op: "is", value: false },
    ],
  };

  it("round-trips any text, URL-safe", () => {
    const text = encodeFilter(f);
    expect(text).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeFilter(text)).toEqual(f);
  });

  it("ignores a damaged filter", () => {
    expect(decodeFilter("not-a-filter")).toBeNull();
    expect(decodeFilter(encodeFilter({ ...f, sort: "price" as "created" }))).toBeNull();
  });

  it("labels chips in plain words", () => {
    expect(chipLabel({ field: "printed", op: "is", value: false })).toBe("Printed: no");
    expect(chipLabel({ field: "due_date", op: "between", value: ["2026-10-26", "2026-11-01"] })).toBe(
      "Due between 2026-10-26 to 2026-11-01",
    );
  });
});
