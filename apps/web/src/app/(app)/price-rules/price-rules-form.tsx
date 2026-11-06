"use client";

import { useActionState } from "react";

import type { Material, PriceRules } from "@/lib/engine";

import { createPriceRules, type PriceFormState } from "./actions";

const INITIAL: PriceFormState = { errors: [] };

function Rate({ name, label, value }: { name: string; label: string; value: number | undefined }) {
  return (
    <label>
      {label}
      <input name={name} type="number" min={0} step={1} required defaultValue={value ?? ""} />
    </label>
  );
}

export function PriceRulesForm({
  current,
  materials,
  idempotencyKey,
}: {
  current: PriceRules | undefined;
  materials: Material[];
  idempotencyKey: string;
}) {
  const [state, action, pending] = useActionState(createPriceRules, INITIAL);
  return (
    <form action={action} className="stack" aria-label="New price version">
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
      <label>
        Effective from
        <input type="date" name="effective_from" required />
      </label>
      <div className="rates">
        <Rate name="setup_cents" label="Setup per line (cents)" value={current?.setup_cents} />
        <Rate name="rush_multiplier_percent" label="Rush multiplier (%)" value={current?.rush_multiplier_percent} />
      </div>
      <fieldset>
        <legend>Material (cents per gram)</legend>
        <div className="rates">
          {materials.map((m) => (
            <div key={m.code}>
              <input type="hidden" name="material_codes" value={m.code} />
              <Rate name={`material_${m.code}`} label={m.name} value={current?.material_cents_per_gram[m.code]} />
            </div>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Machine time (cents per minute)</legend>
        <div className="rates">
          <Rate name="machine_fdm" label="FDM" value={current?.machine_cents_per_minute.fdm} />
          <Rate name="machine_resin" label="Resin" value={current?.machine_cents_per_minute.resin} />
          <Rate name="machine_cnc" label="CNC" value={current?.machine_cents_per_minute.cnc} />
        </div>
      </fieldset>
      <fieldset>
        <legend>Post-processing (cents per part)</legend>
        <div className="rates">
          <Rate name="post_sanding" label="Sanding" value={current?.post_process_cents_per_part.sanding} />
          <Rate name="post_painting" label="Painting" value={current?.post_process_cents_per_part.painting} />
          <Rate name="post_assembly" label="Assembly" value={current?.post_process_cents_per_part.assembly} />
        </div>
      </fieldset>
      <label>
        Note
        <input name="note" maxLength={500} />
      </label>
      <button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Add price version"}
      </button>
    </form>
  );
}
