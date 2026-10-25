"use client";

import { useActionState, useState } from "react";

import type { Material, QuoteDetail, QuoteLine } from "@/lib/engine";

import { decideQuote, saveQuote, type FormState } from "./actions";

const INITIAL: FormState = { errors: [] };
const POST_PROCESSING = ["sanding", "painting", "assembly"] as const;

function Errors({ state }: { state: FormState }) {
  if (state.errors.length === 0) return null;
  return (
    <div role="alert" className="error-box">
      <p>Please fix the following:</p>
      <ul>
        {state.errors.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    </div>
  );
}

/** Where a value came from: shown as text, not only colour, so it is accessible. */
function SourceTag({ line, field }: { line?: QuoteLine; field: string }) {
  const source = line?.sources[field] ?? "missing";
  const uncertain = line?.uncertain.includes(field) ?? false;
  return (
    <>
      <span className={`source source-${source}`}>{{ ai: "AI", staff: "Staff", missing: "Missing" }[source]}</span>
      {uncertain ? <span className="source source-uncertain">Check</span> : null}
    </>
  );
}

type Row = { id: number; line?: QuoteLine };

export function ReviewForm({
  quote,
  materials,
  editKey,
}: {
  quote: QuoteDetail;
  materials: Material[];
  editKey: string;
}) {
  const [state, action, pending] = useActionState(saveQuote, INITIAL);
  const [rows, setRows] = useState<Row[]>(
    quote.lines.length > 0 ? quote.lines.map((line, i) => ({ id: i, line })) : [{ id: 0 }],
  );
  const [nextId, setNextId] = useState(rows.length);

  return (
    <form action={action} className="stack" aria-label="Edit quote">
      <input type="hidden" name="quote_number" value={quote.quote_number} />
      <input type="hidden" name="idempotency_key" value={editKey} />
      <Errors state={state} />

      <label className={quote.due_date ? "" : "field-missing"}>
        <span>
          Due date
          {quote.due_date ? null : <span className="source source-missing">Missing</span>}
        </span>
        <input type="date" name="due_date" defaultValue={quote.due_date ?? ""} />
      </label>
      <label className="inline">
        <input type="checkbox" name="rush" defaultChecked={quote.rush} />
        Rush order
      </label>
      <label>
        Notes
        <textarea name="notes" rows={2} maxLength={2000} defaultValue={quote.notes} />
      </label>

      <fieldset>
        <legend>Lines</legend>
        {rows.map(({ id, line }, index) => {
          const n = index + 1;
          const missing = (field: keyof QuoteLine) => (line?.[field] == null ? "field-missing" : "");
          return (
            <div key={id} className="quote-line">
              <input type="hidden" name="line_ids" value={id} />
              <label>
                <span>
                  Part <SourceTag line={line} field="part_name" />
                </span>
                <input name={`line_${id}_part_name`} defaultValue={line?.part_name ?? ""} aria-label={`Line ${n} part`} />
              </label>
              <label className={missing("quantity")}>
                <span>
                  Quantity <SourceTag line={line} field="quantity" />
                </span>
                <input
                  name={`line_${id}_quantity`}
                  type="number"
                  min={1}
                  defaultValue={line?.quantity ?? ""}
                  aria-label={`Line ${n} quantity`}
                />
              </label>
              <label className={missing("material_code")}>
                <span>
                  Material <SourceTag line={line} field="material" />
                </span>
                <select
                  name={`line_${id}_material_code`}
                  defaultValue={line?.material_code ?? ""}
                  aria-label={`Line ${n} material`}
                >
                  <option value="">Not chosen</option>
                  {materials.map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.name}
                    </option>
                  ))}
                </select>
                {line?.material_as_written ? <span className="muted">Customer wrote: “{line.material_as_written}”</span> : null}
              </label>
              <label className={missing("grams_per_part")}>
                <span>
                  Grams per part <SourceTag line={line} field="grams_per_part" />
                </span>
                <input
                  name={`line_${id}_grams_per_part`}
                  type="number"
                  min={1}
                  defaultValue={line?.grams_per_part ?? ""}
                  aria-label={`Line ${n} grams per part`}
                />
              </label>
              <label className={missing("minutes_per_part")}>
                <span>
                  Minutes per part <SourceTag line={line} field="minutes_per_part" />
                </span>
                <input
                  name={`line_${id}_minutes_per_part`}
                  type="number"
                  min={1}
                  defaultValue={line?.minutes_per_part ?? ""}
                  aria-label={`Line ${n} minutes per part`}
                />
              </label>
              <div className="checks" role="group" aria-label={`Line ${n} post-processing`}>
                {POST_PROCESSING.map((kind) => (
                  <label key={kind} className="inline">
                    <input
                      type="checkbox"
                      name={`line_${id}_post_processing`}
                      value={kind}
                      defaultChecked={line?.post_processing.includes(kind) ?? false}
                    />
                    {kind}
                  </label>
                ))}
              </div>
              {rows.length > 1 ? (
                <button type="button" className="link-button" onClick={() => setRows(rows.filter((r) => r.id !== id))}>
                  Remove line {n}
                </button>
              ) : null}
            </div>
          );
        })}
        <button
          type="button"
          className="link-button"
          onClick={() => {
            setRows([...rows, { id: nextId }]);
            setNextId(nextId + 1);
          }}
        >
          Add line
        </button>
      </fieldset>

      <button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Save and reprice"}
      </button>
    </form>
  );
}

export function DecisionForm({ quoteNumber, decideKey }: { quoteNumber: string; decideKey: string }) {
  const [state, action, pending] = useActionState(decideQuote, INITIAL);
  return (
    <form action={action} className="stack" aria-label="Decide">
      <input type="hidden" name="quote_number" value={quoteNumber} />
      <input type="hidden" name="idempotency_key" value={decideKey} />
      <Errors state={state} />
      <div className="actions">
        <button type="submit" name="decision" value="approve" disabled={pending}>
          Approve and create order
        </button>
        <button type="submit" name="decision" value="reject" className="button-secondary" disabled={pending}>
          Reject
        </button>
      </div>
    </form>
  );
}
