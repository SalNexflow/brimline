import type { components } from "./engine-api";

export type TaskMark = components["schemas"]["TaskMark"];
export type FailureReason = NonNullable<TaskMark["failure_reason"]>;

/** Why an attempt failed, in the operator's words. The engine checks the same list. */
export const FAILURE_REASONS: Record<FailureReason, string> = {
  warping: "Warping",
  bed_adhesion: "Came off the bed",
  layer_shift: "Layer shift",
  clog: "Nozzle clog",
  spaghetti: "Spaghetti (print collapsed)",
  damaged_in_finishing: "Damaged in finishing",
  other: "Other",
};

export type ParsedMark = { ok: true; mark: TaskMark | null } | { ok: false; error: string };

/** What the operator recorded with Done or Failed: a reason for a failure, and grams used for a
 * print or machining task (optional; the report assumes the quote's grams when left empty). */
export function parseTaskMark(action: string, form: FormData): ParsedMark {
  const mark: TaskMark = {};
  const grams = String(form.get("material_used_g") ?? "").trim();
  if (grams !== "") {
    if (!/^\d+$/.test(grams) || Number(grams) < 1 || Number(grams) > 1_000_000) {
      return { ok: false, error: "Grams used must be a whole number from 1 to 1,000,000, or left empty." };
    }
    mark.material_used_g = Number(grams);
  }
  if (action === "fail") {
    const reason = String(form.get("failure_reason") ?? "");
    if (!(reason in FAILURE_REASONS)) return { ok: false, error: "Choose why it failed." };
    mark.failure_reason = reason as FailureReason;
    const note = String(form.get("failure_note") ?? "").trim();
    if (note) mark.failure_note = note.slice(0, 500);
  }
  return { ok: true, mark: Object.keys(mark).length ? mark : null };
}
