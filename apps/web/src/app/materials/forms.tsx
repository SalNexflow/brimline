"use client";

import { useActionState } from "react";

import { receivePurchaseOrder, recordPurchaseOrder, type PoFormState } from "./actions";

const INITIAL: PoFormState = { errors: [] };

function Errors({ errors }: { errors: string[] }) {
  if (errors.length === 0) return null;
  return (
    <div role="alert" className="error-box">
      <ul>
        {errors.map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
    </div>
  );
}

type Prefill = { material?: string; grams?: number; supplier?: string };

/** A person records an order they placed elsewhere, so planning counts its delivery. */
export function PurchaseOrderForm({
  materials,
  timeZone,
  idempotencyKey,
  prefill,
}: {
  materials: string[];
  timeZone: string;
  idempotencyKey: string;
  prefill: Prefill;
}) {
  const [state, action, pending] = useActionState(recordPurchaseOrder, INITIAL);
  return (
    <form action={action} className="stack" aria-label="Record a purchase order">
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <input type="hidden" name="time_zone" value={timeZone} />
      <Errors errors={state.errors} />
      <label>
        Material
        <select name="material_code" required defaultValue={prefill.material ?? ""}>
          <option value="" disabled>
            Choose a material
          </option>
          {materials.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      <label>
        Grams
        <input name="grams" inputMode="numeric" pattern="[0-9]*" required defaultValue={prefill.grams ?? ""} />
      </label>
      <label>
        Supplier
        <input name="supplier" maxLength={100} required defaultValue={prefill.supplier ?? ""} />
      </label>
      <label>
        Expected delivery (shop time)
        <input type="datetime-local" name="expected_at" required />
      </label>
      <button type="submit" disabled={pending}>
        {pending ? "Recording…" : "Record purchase order"}
      </button>
    </form>
  );
}

export function ReceiveButton({ number, idempotencyKey }: { number: string; idempotencyKey: string }) {
  const [state, action, pending] = useActionState(receivePurchaseOrder, INITIAL);
  return (
    <form action={action}>
      <input type="hidden" name="number" value={number} />
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      <Errors errors={state.errors} />
      <button type="submit" className="button-secondary" disabled={pending} aria-label={`Mark ${number} received`}>
        {pending ? "Saving…" : "Received"}
      </button>
    </form>
  );
}
