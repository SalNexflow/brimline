import { describe, expect, it } from "vitest";

import { eventsFromForm } from "./disruption-form";

const TZ = "Europe/Berlin";

function form(fields: Record<string, string>): FormData {
  const f = new FormData();
  for (const [k, v] of Object.entries(fields)) f.set(k, v);
  return f;
}

describe("eventsFromForm", () => {
  it("reads a machine down until 17:00 shop time as UTC", () => {
    const r = eventsFromForm(form({ e0_type: "machine_down", e0_machine: "FDM-3", e0_ends_at: "2026-10-26T17:00" }), TZ);
    expect(r).toEqual({
      ok: true,
      events: [
        {
          type: "machine_down",
          machine: "FDM-3",
          material: null,
          order: null,
          line: null,
          starts_at: null,
          ends_at: "2026-10-26T16:00:00.000Z",
        },
      ],
    });
  });

  it("ignores fields a type does not use", () => {
    const r = eventsFromForm(form({ e0_type: "rush_job", e0_order: "BL-0007", e0_machine: "FDM-1", e0_ends_at: "2026-10-26T17:00" }), TZ);
    expect(r.ok && r.events[0]).toMatchObject({ order: "BL-0007", machine: null, ends_at: null });
  });

  it("asks for what a type needs", () => {
    const r = eventsFromForm(form({ e0_type: "material_delayed", e0_material: "PLA-BLACK" }), TZ);
    expect(r).toEqual({ ok: false, errors: ["Event 1 (Material delayed): a time is needed."] });
  });

  it("refuses an end before the start", () => {
    const r = eventsFromForm(
      form({ e0_type: "machine_down", e0_machine: "FDM-1", e0_starts_at: "2026-10-26T15:00", e0_ends_at: "2026-10-26T14:00" }),
      TZ,
    );
    expect(r.ok).toBe(false);
  });

  it("leaves out events set to 'leave out' and needs at least one", () => {
    expect(eventsFromForm(form({ e0_type: "" }), TZ)).toEqual({ ok: false, errors: ["Give at least one event."] });
  });

  it("reads a cancellation of one line", () => {
    const r = eventsFromForm(form({ e1_type: "cancellation", e1_order: "BL-0004", e1_line: "2" }), TZ);
    expect(r.ok && r.events).toEqual([
      { type: "cancellation", machine: null, material: null, order: "BL-0004", line: 2, starts_at: null, ends_at: null },
    ]);
  });
});
