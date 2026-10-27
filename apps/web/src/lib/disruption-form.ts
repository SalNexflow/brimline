// The disruption event editor's form, read into the engine's events. The engine validates again;
// this only catches what a person can fix before sending (and keeps the times in shop time).

import type { DisruptionEvent } from "./engine";
import { shopLocalToUtc } from "./timeline";

export const EVENT_TYPES = ["machine_down", "material_delayed", "rush_job", "cancellation", "print_overrun"] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export const EVENT_LABELS: Record<EventType, string> = {
  machine_down: "Machine down",
  material_delayed: "Material delayed",
  rush_job: "Rush order",
  cancellation: "Cancellation",
  print_overrun: "Print running over",
};

/** Which fields each type uses; the editor shows only these. */
export const FIELDS: Record<EventType, ("machine" | "material" | "order" | "line" | "starts_at" | "ends_at")[]> = {
  machine_down: ["machine", "starts_at", "ends_at"],
  material_delayed: ["material", "ends_at"],
  rush_job: ["order"],
  cancellation: ["order", "line"],
  print_overrun: ["machine", "ends_at"],
};

const REQUIRED: Record<EventType, string[]> = {
  machine_down: ["machine"],
  material_delayed: ["material", "ends_at"],
  rush_job: ["order"],
  cancellation: ["order"],
  print_overrun: ["machine", "ends_at"],
};

export const MAX_EVENTS = 3;

type Parsed = { ok: true; events: DisruptionEvent[] } | { ok: false; errors: string[] };

export function eventsFromForm(form: FormData, timeZone: string): Parsed {
  const events: DisruptionEvent[] = [];
  const errors: string[] = [];
  for (let i = 0; i < MAX_EVENTS; i++) {
    const get = (name: string) => String(form.get(`e${i}_${name}`) ?? "").trim();
    const type = get("type") as EventType | "";
    if (!type) continue; // "leave out"
    if (!EVENT_TYPES.includes(type)) {
      errors.push(`Event ${i + 1}: unknown type.`);
      continue;
    }
    const label = `Event ${i + 1} (${EVENT_LABELS[type]})`;
    const uses = FIELDS[type];
    const text = (name: "machine" | "material" | "order") => (uses.includes(name) && get(name)) || null;
    const time = (name: "starts_at" | "ends_at") => {
      const raw = uses.includes(name) ? get(name) : "";
      if (!raw) return null;
      const utc = shopLocalToUtc(raw, timeZone);
      if (utc === null) errors.push(`${label}: "${raw}" is not a date and time.`);
      return utc;
    };
    const lineRaw = uses.includes("line") ? get("line") : "";
    const line = lineRaw ? Number(lineRaw) : null;
    if (line !== null && (!Number.isInteger(line) || line < 1)) errors.push(`${label}: line must be 1 or more.`);
    const event: DisruptionEvent = {
      type,
      machine: text("machine"),
      material: text("material"),
      order: text("order"),
      line,
      starts_at: time("starts_at"),
      ends_at: time("ends_at"),
    };
    for (const field of REQUIRED[type]) {
      if (event[field as keyof DisruptionEvent] === null) {
        errors.push(`${label}: ${field === "ends_at" ? "a time" : field} is needed.`);
      }
    }
    if (event.starts_at && event.ends_at && event.ends_at <= event.starts_at) {
      errors.push(`${label}: it ends before it starts.`);
    }
    events.push(event);
  }
  if (events.length === 0 && errors.length === 0) errors.push("Give at least one event.");
  return errors.length ? { ok: false, errors } : { ok: true, events };
}
