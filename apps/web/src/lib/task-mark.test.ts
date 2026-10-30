import { describe, expect, test } from "vitest";

import { parseTaskMark } from "./task-mark";

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [name, value] of Object.entries(fields)) data.append(name, value);
  return data;
}

describe("parseTaskMark", () => {
  test("a plain Done sends nothing extra", () => {
    expect(parseTaskMark("done", form({}))).toEqual({ ok: true, mark: null });
  });

  test("grams are sent as a whole number, and may be left empty", () => {
    expect(parseTaskMark("done", form({ material_used_g: " 150 " }))).toEqual({ ok: true, mark: { material_used_g: 150 } });
    expect(parseTaskMark("done", form({ material_used_g: "" }))).toEqual({ ok: true, mark: null });
    expect(parseTaskMark("done", form({ material_used_g: "12.5" })).ok).toBe(false);
    expect(parseTaskMark("done", form({ material_used_g: "0" })).ok).toBe(false);
  });

  test("a failure needs one of the listed reasons", () => {
    expect(parseTaskMark("fail", form({}))).toEqual({ ok: false, error: "Choose why it failed." });
    expect(parseTaskMark("fail", form({ failure_reason: "melted" })).ok).toBe(false);
    expect(parseTaskMark("fail", form({ failure_reason: "warping", failure_note: "  corner lifted ", material_used_g: "50" }))).toEqual({
      ok: true,
      mark: { failure_reason: "warping", failure_note: "corner lifted", material_used_g: 50 },
    });
  });
});
