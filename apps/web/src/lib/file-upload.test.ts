import { describe, expect, it } from "vitest";

import { MAX_UPLOAD_BYTES, parseUpload, splitJobKey } from "./file-upload";

function form(fields: Record<string, string>, file?: File): FormData {
  const data = new FormData();
  for (const [k, v] of Object.entries(fields)) data.set(k, v);
  if (file) data.set("file", file);
  return data;
}

const stl = new File([new Uint8Array(84)], "bracket.stl");

describe("parseUpload", () => {
  it("accepts a file for a quote line", () => {
    const r = parseUpload(form({ quote: "Q-0003", line: "1", unit: "millimeter" }, stl));
    expect(r).toEqual({
      ok: true,
      value: { quote: "Q-0003", order: null, line: 1, unit: "millimeter", filename: "bracket.stl", size: 84 },
    });
  });

  it("accepts a file for a job, in inches", () => {
    const r = parseUpload(form({ order: "BL-0008", line: "2", unit: "inch" }, new File(["x"], "HILT.3MF")));
    expect(r.ok && r.value.order).toBe("BL-0008");
  });

  it("refuses other formats, empty files and missing targets", () => {
    const r = parseUpload(form({ line: "1", unit: "millimeter" }, new File([], "part.obj")));
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.errors).toContain("Only STL and 3MF files can be checked");
      expect(r.errors).toContain("The file is empty");
      expect(r.errors).toContain("Give either a quote or an order");
    }
  });

  it("refuses a file over the engine's limit", () => {
    const big = { name: "big.stl", size: MAX_UPLOAD_BYTES + 1 } as File;
    const data = form({ quote: "Q-0001", line: "1", unit: "millimeter" });
    data.set("file", new Blob(["x"]), "big.stl");
    const fake = { get: (k: string) => (k === "file" ? big : data.get(k)) } as unknown as FormData;
    const r = parseUpload(fake);
    expect(r.ok === false && r.errors).toEqual(["The file is larger than 25 MiB"]);
  });

  it("refuses an unknown unit, and both targets at once", () => {
    const unit = parseUpload(form({ quote: "Q-0001", line: "1", unit: "furlong" }, stl));
    expect(unit.ok === false && unit.errors).toEqual(["Choose a unit"]);
    const both = parseUpload(form({ quote: "Q-0001", order: "BL-0001", line: "1", unit: "inch" }, stl));
    expect(both.ok === false && both.errors).toEqual(["Give either a quote or an order"]);
  });
});

describe("splitJobKey", () => {
  it("splits a board job key", () => {
    expect(splitJobKey("BL-0008-2")).toEqual({ order: "BL-0008", line: 2 });
    expect(splitJobKey("nonsense")).toBeNull();
  });
});
