"use client";

import { useActionState, useState } from "react";

import type { Customer, Material } from "@/lib/engine";

import { createOrder, type CreateOrderState } from "./actions";

type Props = {
  idempotencyKey: string;
  materials: Material[];
  // Staff choose a customer; a customer can only order for themselves.
  customers: Customer[] | null;
  ownCustomer: Customer | null;
};

const INITIAL: CreateOrderState = { errors: [] };

export function OrderForm({ idempotencyKey, materials, customers, ownCustomer }: Props) {
  const [state, action, pending] = useActionState(createOrder, INITIAL);
  const [lineIds, setLineIds] = useState([0]);
  const [nextId, setNextId] = useState(1);

  const addLine = () => {
    setLineIds([...lineIds, nextId]);
    setNextId(nextId + 1);
  };

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
          Ordering for <strong>{ownCustomer.name}</strong>
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
        Due date
        <input type="date" name="due_date" required />
      </label>

      <label className="inline">
        <input type="checkbox" name="rush" />
        Rush order
      </label>

      <label>
        Notes
        <textarea name="notes" rows={3} maxLength={2000} />
      </label>

      <fieldset>
        <legend>Lines</legend>
        {lineIds.map((id, index) => (
          <div key={id} className="line-row">
            <label>
              Part name
              <input name="line_part_name" aria-label={`Line ${index + 1} part name`} />
            </label>
            <label>
              Quantity
              <input
                name="line_quantity"
                type="number"
                min={1}
                max={10000}
                aria-label={`Line ${index + 1} quantity`}
              />
            </label>
            <label>
              Material
              <select
                name="line_material_code"
                defaultValue=""
                aria-label={`Line ${index + 1} material`}
              >
                <option value="" disabled>
                  Choose
                </option>
                {materials.map((material) => (
                  <option key={material.code} value={material.code}>
                    {material.name}
                  </option>
                ))}
              </select>
            </label>
            {lineIds.length > 1 ? (
              <button
                type="button"
                className="link-button"
                onClick={() => setLineIds(lineIds.filter((other) => other !== id))}
              >
                Remove
              </button>
            ) : null}
          </div>
        ))}
        <button type="button" className="link-button" onClick={addLine}>
          Add line
        </button>
      </fieldset>

      <button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Create order"}
      </button>
    </form>
  );
}
