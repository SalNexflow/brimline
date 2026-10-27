"use client";

import { useActionState } from "react";

import { actOnTask, type ActionState } from "./actions";

const INITIAL: ActionState = { error: null };
const TEXT = { start: "Start", done: "Done", fail: "Failed" } as const;
type Action = keyof typeof TEXT;

type Props = { taskId: number; label: string; actions: Action[]; keys: Record<Action, string> };

/** The buttons for one task, one small form each. Each button names its task, so a screen
 * reader hears "Start: Prep for BL-0003 Model tray" rather than a row of bare "Start"s. */
export function TaskActions({ taskId, label, actions, keys }: Props) {
  const [state, formAction, pending] = useActionState(actOnTask, INITIAL);
  return (
    <div className="task-actions">
      {actions.map((a) => (
        <form key={a} action={formAction}>
          <input type="hidden" name="task_id" value={taskId} />
          <input type="hidden" name="action" value={a} />
          <input type="hidden" name="idempotency_key" value={keys[a]} />
          <button
            type="submit"
            className={a === "fail" ? "button-secondary" : undefined}
            disabled={pending}
            aria-label={`${TEXT[a]}: ${label}`}
          >
            {TEXT[a]}
          </button>
        </form>
      ))}
      {state.error ? (
        <p role="alert" className="error-box">
          {state.error}
        </p>
      ) : null}
    </div>
  );
}
