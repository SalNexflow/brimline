"use client";

import { useActionState } from "react";

import { testConnection, type TestState } from "./actions";
import { milliseconds } from "./view";

const INITIAL: TestState = { error: null, result: null };

/** What a test found, in words. The machine's own text is quoted, never interpreted. */
export function describeTest(r: NonNullable<TestState["result"]>): string {
  if (!r.ok) return `${r.machine} did not answer usably (${r.response_ms} ms): ${r.error}`;
  return `${r.machine} answered in ${milliseconds(r.response_ms)} (${r.state ?? "no state"}).`;
}

export function TestConnectionForm({ code, idempotencyKey }: { code: string; idempotencyKey: string }) {
  const [state, action, pending] = useActionState(testConnection, INITIAL);
  return (
    <form action={action} className="inline-form" aria-label={`Test the connection to ${code}`}>
      <input type="hidden" name="code" value={code} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <button type="submit" className="button-secondary" disabled={pending}>
        {pending ? "Testing…" : "Test connection"}{" "}
        <span className="visually-hidden">to {code}</span>
      </button>
      {state.result ? (
        <p role="status" className="muted" data-testid="test-result">
          {describeTest(state.result)}
        </p>
      ) : null}
      {state.error ? (
        <p role="alert" className="error-box">
          {state.error}
        </p>
      ) : null}
    </form>
  );
}
