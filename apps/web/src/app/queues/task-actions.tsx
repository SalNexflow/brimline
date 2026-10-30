"use client";

import { useActionState, useId } from "react";

import { FAILURE_REASONS } from "@/lib/task-mark";

import { actOnTask, type ActionState } from "./actions";

const INITIAL: ActionState = { error: null };
const TEXT = { start: "Start", done: "Done", fail: "Failed" } as const;
type Action = keyof typeof TEXT;

type Props = { taskId: number; kind: string; label: string; actions: Action[]; keys: Record<Action, string> };

/** The buttons for one task, one small form each. Each button names its task, so a screen
 * reader hears "Start: Prep for BL-0003 Model tray" rather than a row of bare "Start"s.
 * Done and Failed on a print or machining task can record the grams used (M10); Failed asks why. */
export function TaskActions({ taskId, kind, label, actions, keys }: Props) {
  const [state, formAction, pending] = useActionState(actOnTask, INITIAL);
  const id = useId();
  const grams = (a: Action) =>
    kind === "machine" ? (
      <label className="inline-field">
        Grams used <span className="muted">(optional)</span>
        <input name="material_used_g" inputMode="numeric" pattern="[0-9]*" size={6} aria-label={`Grams used: ${label} (${TEXT[a]})`} />
      </label>
    ) : null;
  const hidden = (a: Action) => (
    <>
      <input type="hidden" name="task_id" value={taskId} />
      <input type="hidden" name="action" value={a} />
      <input type="hidden" name="idempotency_key" value={keys[a]} />
    </>
  );
  return (
    <div className="task-actions">
      {actions.map((a) =>
        a === "fail" ? (
          <details key={a}>
            <summary className="button-secondary">{TEXT[a]}…</summary>
            <form action={formAction} className="fail-form">
              {hidden(a)}
              <label htmlFor={`${id}-reason`}>Why did it fail?</label>
              <select id={`${id}-reason`} name="failure_reason" required defaultValue="">
                <option value="" disabled>
                  Choose a reason
                </option>
                {Object.entries(FAILURE_REASONS).map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </select>
              <label htmlFor={`${id}-note`}>Note (optional)</label>
              <input id={`${id}-note`} name="failure_note" maxLength={500} />
              {grams(a)}
              <button type="submit" className="button-secondary" disabled={pending} aria-label={`Record failure: ${label}`}>
                Record failure
              </button>
            </form>
          </details>
        ) : (
          <form key={a} action={formAction}>
            {hidden(a)}
            {a === "done" ? grams(a) : null}
            <button type="submit" disabled={pending} aria-label={`${TEXT[a]}: ${label}`}>
              {TEXT[a]}
            </button>
          </form>
        ),
      )}
      {state.error ? (
        <p role="alert" className="error-box">
          {state.error}
        </p>
      ) : null}
    </div>
  );
}
