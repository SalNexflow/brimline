"use client";

import { useActionState } from "react";

import type { Customer } from "@/lib/engine";

import { submitQuoteRequest, type SubmitState } from "./actions";

type Props = {
  idempotencyKey: string;
  customers: Customer[] | null; // staff choose; a customer always asks for themselves
  ownCustomer: Customer | null;
};

const INITIAL: SubmitState = { errors: [] };

export function RequestForm({ idempotencyKey, customers, ownCustomer }: Props) {
  const [state, action, pending] = useActionState(submitQuoteRequest, INITIAL);
  return (
    <form action={action} className="stack">
      <input type="hidden" name="idempotency_key" value={idempotencyKey} />
      {state.errors.length > 0 ? (
        <div role="alert" className="error-box">
          <p>Please fix the following:</p>
          <ul>
            {state.errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {ownCustomer ? (
        <p>
          Request for <strong>{ownCustomer.name}</strong>
          <input type="hidden" name="customer_code" value={ownCustomer.code} />
        </p>
      ) : (
        <label>
          Customer
          <select name="customer_code" defaultValue="" required>
            <option value="" disabled>
              Choose a customer
            </option>
            {(customers ?? []).map((customer) => (
              <option key={customer.code} value={customer.code}>
                {customer.name}
              </option>
            ))}
          </select>
        </label>
      )}

      <label>
        Message
        <textarea
          name="message"
          rows={8}
          maxLength={10000}
          required
          placeholder="For example: 20 phone stands, black PETG, need by Friday."
        />
      </label>
      <p className="muted">
        The message is read by an AI model to draft a quote. Staff check every detail, and the shop
        calculates the price; the model never sets prices or dates.
      </p>
      <button type="submit" disabled={pending}>
        {pending ? "Reading the message…" : "Send request"}
      </button>
    </form>
  );
}
