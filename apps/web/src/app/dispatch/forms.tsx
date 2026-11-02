"use client";

import { useActionState } from "react";

import { askDispatcher, proceedWith, setSimulation, type DispatchState } from "./actions";

const INITIAL: DispatchState = { error: null };

function Problem({ state }: { state: DispatchState }) {
  return state.error ? (
    <p role="alert" className="error-box">
      {state.error}
    </p>
  ) : null;
}

export function AskButton({ idempotencyKey }: { idempotencyKey: string }) {
  const [state, action, pending] = useActionState(askDispatcher, INITIAL);
  return (
    <form action={action} className="ask-form">
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <Problem state={state} />
      <button type="submit" disabled={pending}>
        {pending ? "Asking…" : "Ask the dispatcher"}
      </button>
    </form>
  );
}

export type ProposalRow = { id: number; label: string; detail: string; selectable: boolean };

export function ProceedForm({ runId, proposals, idempotencyKey }: { runId: number; proposals: ProposalRow[]; idempotencyKey: string }) {
  const [state, action, pending] = useActionState(proceedWith, INITIAL);
  return (
    <form action={action} className="stack" aria-label="Approve proposals">
      <input type="hidden" name="run_id" value={runId} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <Problem state={state} />
      <fieldset className="proposals">
        <legend>Proposals</legend>
        {proposals.map((p) => (
          <div key={p.id} className="proposal">
            <label className="inline">
              <input type="checkbox" name="proposal_id" value={p.id} disabled={!p.selectable} />
              {p.label}
            </label>
            <p className="muted">{p.detail}</p>
          </div>
        ))}
      </fieldset>
      <button type="submit" disabled={pending || !proposals.some((p) => p.selectable)}>
        {pending ? "Carrying out…" : "Proceed"}
      </button>
    </form>
  );
}

export function SimulationForm({ code, idempotencyKey }: { code: string; idempotencyKey: string }) {
  const [state, action, pending] = useActionState(setSimulation, INITIAL);
  return (
    <form action={action} className="stack" aria-label={`Simulation of ${code}`}>
      <input type="hidden" name="code" value={code} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <Problem state={state} />
      <label>
        Behaviour
        <select name="mode" defaultValue="success">
          <option value="success">Works normally</option>
          <option value="failure">Refuses to start</option>
          <option value="slow">Answers slowly</option>
          <option value="unresponsive">Stops answering</option>
        </select>
      </label>
      <label className="inline">
        <input type="checkbox" name="busy" /> Busy with someone else&apos;s job
      </label>
      <label>
        Message the machine reports
        <input name="message" maxLength={300} />
      </label>
      <button type="submit" className="button-secondary" disabled={pending}>
        Set simulation
      </button>
    </form>
  );
}
