"use client";

import { useActionState, useState } from "react";

import { UNITS } from "@/lib/file-upload";

import { acceptWarning, askAdvice, uploadModel, type FormState } from "./actions";

const INITIAL: FormState = { errors: [] };

function Errors({ state }: { state: FormState }) {
  if (state.errors.length === 0) return null;
  return (
    <div role="alert" className="error-box">
      <ul>
        {state.errors.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    </div>
  );
}

const UNIT_LABELS: Record<(typeof UNITS)[number], string> = {
  millimeter: "millimetres (most files)",
  inch: "inches",
  centimeter: "centimetres",
  meter: "metres",
  micron: "microns",
  foot: "feet",
};

export function UploadForm({
  quote,
  order,
  line,
  uploadKey,
  maxBytes,
}: {
  quote?: string;
  order?: string;
  line: number;
  uploadKey: string;
  maxBytes: number;
}) {
  const [state, action, pending] = useActionState(uploadModel, INITIAL);
  const [tooBig, setTooBig] = useState<string | null>(null);
  const mib = (maxBytes / 1024 / 1024).toFixed(maxBytes < 10 * 1024 * 1024 ? 1 : 0);
  return (
    <form action={action} className="stack" aria-label="Upload a model file">
      <input type="hidden" name="quote" value={quote ?? ""} />
      <input type="hidden" name="order" value={order ?? ""} />
      <input type="hidden" name="line" value={line} />
      <input type="hidden" name="idempotency_key" value={uploadKey} />
      <Errors state={state} />
      <label>
        Model file (STL or 3MF, up to {mib} MiB)
        <input
          type="file"
          name="file"
          accept=".stl,.3mf"
          required
          onChange={(e) => {
            const f = e.currentTarget.files?.[0];
            // Checked here too: on the hosted demo a larger body never reaches the server.
            setTooBig(f && f.size > maxBytes ? `The file is larger than ${mib} MiB.` : null);
          }}
        />
      </label>
      <label>
        Numbers in an STL file are in
        <select name="unit" defaultValue="millimeter">
          {UNITS.map((u) => (
            <option key={u} value={u}>
              {UNIT_LABELS[u]}
            </option>
          ))}
        </select>
        <span className="muted">A 3MF file states its own unit; this is used for STL only.</span>
      </label>
      {tooBig ? (
        <p role="alert" className="error-box">
          {tooBig}
        </p>
      ) : null}
      <button type="submit" disabled={pending || tooBig !== null}>
        {pending ? "Checking…" : "Upload and check"}
      </button>
    </form>
  );
}

export function AcceptWarningForm({
  fileNumber,
  check,
  formKey,
}: {
  fileNumber: string;
  check: string;
  formKey: string;
}) {
  const [state, action, pending] = useActionState(acceptWarning, INITIAL);
  return (
    <form action={action} className="inline-form" aria-label={`Accept the ${check} warning`}>
      <input type="hidden" name="file_number" value={fileNumber} />
      <input type="hidden" name="check" value={check} />
      <input type="hidden" name="idempotency_key" value={formKey} />
      <Errors state={state} />
      <label>
        Reason
        <input name="reason" minLength={3} maxLength={500} required aria-label={`Reason to accept ${check}`} />
      </label>
      <button type="submit" className="button-secondary" disabled={pending}>
        Accept warning
      </button>
    </form>
  );
}

export function AdviceForm({ fileNumber, formKey }: { fileNumber: string; formKey: string }) {
  const [state, action, pending] = useActionState(askAdvice, INITIAL);
  return (
    <form action={action} aria-label="Ask for AI advice">
      <input type="hidden" name="file_number" value={fileNumber} />
      <input type="hidden" name="idempotency_key" value={formKey} />
      <Errors state={state} />
      <button type="submit" className="button-secondary" disabled={pending}>
        {pending ? "Asking…" : "Ask AI for advice on the preview"}
      </button>
    </form>
  );
}
