// Search filters in the browser (M8): the chips. A chip is one condition; editing chips builds
// a new filter that runs with no model call. The engine checks every filter again and adds the
// permissions itself; this only gives quick, plain messages and keeps the URL readable.

export type FieldName =
  | "order_number"
  | "customer"
  | "order_status"
  | "job_status"
  | "material"
  | "process"
  | "rush"
  | "printed"
  | "can_plan"
  | "overdue"
  | "quantity"
  | "part_name"
  | "notes"
  | "due_date";
export type Op =
  | "in"
  | "is"
  | "eq"
  | "lt"
  | "lte"
  | "gt"
  | "gte"
  | "contains"
  | "on"
  | "before"
  | "after"
  | "on_or_before"
  | "on_or_after"
  | "between";
export type Value = boolean | number | string | string[];
export type Condition = { field: FieldName; op: Op; value: Value };
export type Filter = { conditions: Condition[]; sort: "due_date" | "created" };

type Kind = "codes" | "bool" | "true" | "int" | "text" | "date";

/** The same closed table as the engine (search/filters.py). */
export const FIELDS: Record<FieldName, { label: string; ops: Op[]; kind: Kind }> = {
  order_number: { label: "Order", ops: ["in"], kind: "codes" },
  customer: { label: "Customer", ops: ["in"], kind: "codes" },
  order_status: { label: "Order status", ops: ["in"], kind: "codes" },
  job_status: { label: "Job status", ops: ["in"], kind: "codes" },
  material: { label: "Material", ops: ["in"], kind: "codes" },
  process: { label: "Process", ops: ["in"], kind: "codes" },
  rush: { label: "Rush", ops: ["is"], kind: "bool" },
  printed: { label: "Printed", ops: ["is"], kind: "bool" },
  can_plan: { label: "Can be planned", ops: ["is"], kind: "bool" },
  overdue: { label: "Overdue", ops: ["is"], kind: "true" },
  quantity: { label: "Quantity", ops: ["eq", "lt", "lte", "gt", "gte"], kind: "int" },
  part_name: { label: "Part name", ops: ["contains"], kind: "text" },
  notes: { label: "Order notes", ops: ["contains"], kind: "text" },
  due_date: { label: "Due", ops: ["on", "before", "after", "on_or_before", "on_or_after", "between"], kind: "date" },
};

export const OP_LABELS: Record<Op, string> = {
  in: "is one of",
  is: "is",
  eq: "=",
  lt: "<",
  lte: "≤",
  gt: ">",
  gte: "≥",
  contains: "contains",
  on: "on",
  before: "before",
  after: "after",
  on_or_before: "on or before",
  on_or_after: "on or after",
  between: "between",
};

const ISO = /^\d{4}-\d{2}-\d{2}$/;

/** A chip's typed text as the value its field takes, or a plain error. */
export function parseValue(field: FieldName, op: Op, text: string): { ok: true; value: Value } | { ok: false; error: string } {
  const spec = FIELDS[field];
  if (!spec.ops.includes(op)) return { ok: false, error: `${spec.label} does not take “${OP_LABELS[op]}”` };
  const t = text.trim();
  switch (spec.kind) {
    case "codes": {
      const values = t.split(",").map((v) => v.trim()).filter(Boolean);
      if (values.length === 0) return { ok: false, error: `${spec.label}: give at least one value` };
      return { ok: true, value: values };
    }
    case "bool":
    case "true":
      if (t !== "true" && t !== "false") return { ok: false, error: `${spec.label} is yes or no` };
      if (spec.kind === "true" && t === "false") return { ok: false, error: "Overdue can only be yes" };
      return { ok: true, value: t === "true" };
    case "int": {
      const n = Number(t);
      if (!Number.isInteger(n) || n < 0) return { ok: false, error: "Quantity is a whole number" };
      return { ok: true, value: n };
    }
    case "text":
      if (t.length === 0 || t.length > 100) return { ok: false, error: `${spec.label}: 1 to 100 characters` };
      return { ok: true, value: t };
    case "date": {
      if (op === "between") {
        const [a, b] = t.split(/\s*(?:to|,)\s*/);
        if (!a || !b || !ISO.test(a) || !ISO.test(b)) return { ok: false, error: "Between needs two dates, e.g. 2026-10-26 to 2026-11-01" };
        return { ok: true, value: [a, b] };
      }
      if (!ISO.test(t)) return { ok: false, error: "A date is written YYYY-MM-DD" };
      return { ok: true, value: t };
    }
  }
}

/** The value as a chip shows it, and as its edit box starts. */
export function valueText(c: Condition): string {
  if (Array.isArray(c.value)) return c.op === "between" ? c.value.join(" to ") : c.value.join(", ");
  if (typeof c.value === "boolean") return c.value ? "true" : "false";
  return String(c.value);
}

export function chipLabel(c: Condition): string {
  const spec = FIELDS[c.field];
  if (spec.kind === "bool" || spec.kind === "true") return `${spec.label}: ${c.value ? "yes" : "no"}`;
  return `${spec.label} ${OP_LABELS[c.op]} ${valueText(c)}`;
}

/** URL-safe text for a filter (base64url of its JSON), and back. */
export function encodeFilter(f: Filter): string {
  const bytes = new TextEncoder().encode(JSON.stringify(f));
  let binary = "";
  bytes.forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decodeFilter(text: string): Filter | null {
  try {
    const padded = text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4);
    const binary = atob(padded);
    const json = new TextDecoder().decode(Uint8Array.from(binary, (ch) => ch.charCodeAt(0)));
    const f = JSON.parse(json) as Filter;
    if (!f || !Array.isArray(f.conditions) || (f.sort !== "due_date" && f.sort !== "created")) return null;
    return f;
  } catch {
    return null;
  }
}
