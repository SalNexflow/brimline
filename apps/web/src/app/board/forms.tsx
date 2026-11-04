"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import { decide, planDay, type ActionState } from "./actions";

const INITIAL: ActionState = { error: null };

function ErrorLine({ state }: { state: ActionState }) {
  return state.error ? (
    <p role="alert" className="error-box">
      {state.error}
    </p>
  ) : null;
}

export function PlanDayForm({ idempotencyKey, busy }: { idempotencyKey: string; busy: boolean }) {
  const [state, action, pending] = useActionState(planDay, INITIAL);
  return (
    <form action={action} className="inline-form">
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <button type="submit" disabled={busy || pending} aria-describedby="plan-day-help">
        {busy ? "Planning…" : "Plan day"}
      </button>
      <span id="plan-day-help" className="muted">
        Plans every waiting job from now on. It runs in the background; you can keep using the board.
      </span>
      <ErrorLine state={state} />
    </form>
  );
}

export function DecisionForm({
  scheduleId,
  approveKey,
  discardKey,
  canApprove,
  reason,
  replan,
}: {
  scheduleId: number;
  approveKey: string;
  discardKey: string;
  canApprove: boolean;
  reason: string | null;
  /** Set when the draft is stale: offers "Plan again" right where it says why it cannot be approved. */
  replan?: { idempotencyKey: string; busy: boolean };
}) {
  const [approveState, approveAction, approving] = useActionState(decide, INITIAL);
  const [discardState, discardAction, discarding] = useActionState(decide, INITIAL);
  const [planState, planAction, planning] = useActionState(planDay, INITIAL);
  return (
    <div className="actions">
      <form action={approveAction}>
        <input type="hidden" name="schedule_id" value={scheduleId} />
        <input type="hidden" name="decision" value="approve" />
        <input type="hidden" name="idempotency_key" value={approveKey} />
        <button type="submit" disabled={!canApprove || approving} aria-describedby={reason ? "approve-reason" : undefined}>
          Approve plan
        </button>
      </form>
      <form action={discardAction}>
        <input type="hidden" name="schedule_id" value={scheduleId} />
        <input type="hidden" name="decision" value="discard" />
        <input type="hidden" name="idempotency_key" value={discardKey} />
        <button type="submit" className="button-secondary" disabled={discarding}>
          Discard
        </button>
      </form>
      {reason ? (
        <p id="approve-reason" className="muted">
          {reason}
        </p>
      ) : null}
      {replan ? (
        <form action={planAction}>
          <input type="hidden" name="idempotency_key" value={replan.idempotencyKey} />
          <button type="submit" disabled={replan.busy || planning} aria-describedby={reason ? "approve-reason" : undefined}>
            Plan again
          </button>
        </form>
      ) : null}
      <ErrorLine state={approveState} />
      <ErrorLine state={discardState} />
      <ErrorLine state={planState} />
    </div>
  );
}

/** While a plan is being made, re-render the board every two seconds to show progress (the
    Connectivity tab uses it too, every five). */
export function AutoRefresh({ active, everyMs = 2000 }: { active: boolean; everyMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => router.refresh(), everyMs);
    return () => clearInterval(timer);
  }, [active, everyMs, router]);
  return null;
}
