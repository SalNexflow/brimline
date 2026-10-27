"use client";

import { useActionState, useState } from "react";

import { EVENT_LABELS, EVENT_TYPES, FIELDS, MAX_EVENTS, type EventType } from "@/lib/disruption-form";
import type { DisruptionCatalog, DisruptionEvent } from "@/lib/engine";
import { formatShopTime, utcToShopLocal } from "@/lib/timeline";

import { confirmEvents, dismissDisruption, readMessage, type FormState } from "./disruption-actions";

const INITIAL: FormState = { errors: [] };

function Errors({ state }: { state: FormState }) {
  if (state.errors.length === 0) return null;
  return (
    <div role="alert" className="error-box">
      <ul>
        {state.errors.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </div>
  );
}

export function ReportForm({ idempotencyKey }: { idempotencyKey: string }) {
  const [state, action, pending] = useActionState(readMessage, INITIAL);
  return (
    <form action={action} className="stack report-form">
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <label htmlFor="disruption-message">What happened?</label>
      <textarea
        id="disruption-message"
        name="message"
        rows={2}
        maxLength={2000}
        placeholder="For example: printer 3 jammed until 5pm"
        aria-describedby="disruption-help"
      />
      <p id="disruption-help" className="muted">
        The AI only suggests how to read it. You check every event and time before anything is re-planned,
        and nothing changes until you approve the new plan.
      </p>
      <div>
        <button type="submit" disabled={pending}>
          {pending ? "Reading…" : "Read message"}
        </button>
      </div>
      <Errors state={state} />
    </form>
  );
}

type EditorProps = {
  disruptionId: number | null; // null: entered by hand
  events: DisruptionEvent[];
  choices: Record<string, string[]>; // "<event>:<starts_at|ends_at>" -> two readings of a date
  warnings: string[]; // shown above; confirming needs the planner to tick that they checked them
  catalog: DisruptionCatalog;
  timeZone: string;
  idempotencyKey: string;
  submitLabel: string;
};

/** The events, as read (or blank), for the planner to confirm or correct. */
export function EventEditor({
  disruptionId,
  events,
  choices,
  warnings,
  catalog,
  timeZone,
  idempotencyKey,
  submitLabel,
}: EditorProps) {
  const [state, action, pending] = useActionState(confirmEvents, INITIAL);
  const [types, setTypes] = useState<(EventType | "")[]>(
    Array.from({ length: MAX_EVENTS }, (_, i) => (events[i]?.type as EventType | undefined) ?? ""),
  );
  const prefix = `ev-${disruptionId ?? "hand"}`;
  return (
    <form action={action} className="stack event-editor" aria-label={submitLabel}>
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <input type="hidden" name="disruption_id" value={disruptionId ?? ""} />
      {types.map((type, i) => {
        const e = events[i];
        const uses = type ? FIELDS[type] : [];
        const id = (f: string) => `${prefix}-${i}-${f}`;
        const readingsFor = (f: "starts_at" | "ends_at") => choices[`${i}:${f}`] ?? [];
        const Readings = ({ f }: { f: "starts_at" | "ends_at" }) => {
          const readings = readingsFor(f);
          if (readings.length !== 2) return null;
          return (
            <p className="warning-box" id={id(`${f}-choices`)}>
              The date could mean {formatShopTime(readings[0]!, timeZone)} or {formatShopTime(readings[1]!, timeZone)}.
              Choose one and type it in:{" "}
              {readings.map((r) => (
                <span key={r} className="choice">
                  {utcToShopLocal(r, timeZone).replace("T", " ")}
                </span>
              ))}
            </p>
          );
        };
        // Only the first slot is shown when empty, plus one more for adding.
        if (!type && i > 0 && !types[i - 1]) return null;
        return (
          <fieldset key={i}>
            <legend>Event {i + 1}</legend>
            <label htmlFor={id("type")}>What</label>
            <select
              id={id("type")}
              name={`e${i}_type`}
              value={type}
              onChange={(ev) => setTypes((t) => t.map((x, k) => (k === i ? (ev.target.value as EventType | "") : x)))}
            >
              <option value="">{i === 0 && !disruptionId ? "Choose…" : "Leave out"}</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {EVENT_LABELS[t]}
                </option>
              ))}
            </select>
            {uses.includes("machine") ? (
              <>
                <label htmlFor={id("machine")}>Machine</label>
                <select id={id("machine")} name={`e${i}_machine`} defaultValue={e?.machine ?? ""}>
                  <option value="">Choose…</option>
                  {catalog.machines.map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.code}: {m.name}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            {uses.includes("material") ? (
              <>
                <label htmlFor={id("material")}>Material</label>
                <select id={id("material")} name={`e${i}_material`} defaultValue={e?.material ?? ""}>
                  <option value="">Choose…</option>
                  {catalog.materials.map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.code}: {m.name}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            {uses.includes("order") ? (
              <>
                <label htmlFor={id("order")}>Order</label>
                <select id={id("order")} name={`e${i}_order`} defaultValue={e?.order ?? ""}>
                  <option value="">Choose…</option>
                  {catalog.orders.map((o) => (
                    <option key={o.number} value={o.number}>
                      {o.number}: {o.name}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            {uses.includes("line") ? (
              <>
                <label htmlFor={id("line")}>Line (empty: the whole order)</label>
                <input id={id("line")} name={`e${i}_line`} type="number" min={1} defaultValue={e?.line ?? ""} />
              </>
            ) : null}
            {uses.includes("starts_at") ? (
              <>
                <label htmlFor={id("starts_at")}>From ({timeZone} time; empty: when reported)</label>
                <Readings f="starts_at" />
                <input
                  id={id("starts_at")}
                  name={`e${i}_starts_at`}
                  type="datetime-local"
                  defaultValue={e?.starts_at ? utcToShopLocal(e.starts_at, timeZone) : ""}
                  aria-describedby={readingsFor("starts_at").length === 2 ? id("starts_at-choices") : undefined}
                />
              </>
            ) : null}
            {uses.includes("ends_at") ? (
              <>
                <label htmlFor={id("ends_at")}>
                  {type === "machine_down" ? "Back at" : type === "print_overrun" ? "Done at" : "Available at"} ({timeZone}{" "}
                  time{type === "machine_down" ? "; empty: until further notice" : ""})
                </label>
                <Readings f="ends_at" />
                <input
                  id={id("ends_at")}
                  name={`e${i}_ends_at`}
                  type="datetime-local"
                  defaultValue={e?.ends_at ? utcToShopLocal(e.ends_at, timeZone) : ""}
                  aria-describedby={readingsFor("ends_at").length === 2 ? id("ends_at-choices") : undefined}
                />
              </>
            ) : null}
          </fieldset>
        );
      })}
      {warnings.length > 0 || disruptionId === null ? (
        <label className="inline">
          <input type="checkbox" name="acknowledged" required={warnings.length > 0} />{" "}
          {warnings.length > 0
            ? "I have checked the warnings above."
            : "If this cancels two or more orders or lines: I have checked each one."}
        </label>
      ) : null}
      <div>
        <button type="submit" disabled={pending}>
          {submitLabel}
        </button>
      </div>
      <Errors state={state} />
    </form>
  );
}

export function DismissButton({ disruptionId, idempotencyKey }: { disruptionId: number; idempotencyKey: string }) {
  const [state, action, pending] = useActionState(dismissDisruption, INITIAL);
  return (
    <form action={action}>
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <input type="hidden" name="disruption_id" value={disruptionId} />
      <button type="submit" className="button-secondary" disabled={pending}>
        Dismiss
      </button>
      <Errors state={state} />
    </form>
  );
}
