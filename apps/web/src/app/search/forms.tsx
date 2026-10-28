"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useState } from "react";

import {
  chipLabel,
  encodeFilter,
  FIELDS,
  OP_LABELS,
  parseValue,
  valueText,
  type Condition,
  type FieldName,
  type Filter,
  type Op,
} from "@/lib/search-filter";

import { askSearch, type AskState } from "./actions";

const INITIAL: AskState = { error: null, reason: null, options: [], injection: false };

export function QuestionForm() {
  const [state, action, pending] = useActionState(askSearch, INITIAL);
  return (
    <form action={action} className="stack" aria-label="Ask a question">
      <label>
        Question
        <input
          name="question"
          maxLength={500}
          placeholder="jobs due this week not printed yet"
          aria-describedby="question-help"
        />
      </label>
      <p id="question-help" className="muted">
        AI turns your question into the filter below; the shop&apos;s code works out dates and what you may see.
      </p>
      <button type="submit" disabled={pending}>
        {pending ? "Reading…" : "Search"}
      </button>
      {state.error ? (
        <p role="alert" className="error-box">
          {state.error}
        </p>
      ) : null}
      {state.reason ? (
        <div role="status" className="notice">
          <p>{state.reason}</p>
          {state.options.length > 0 ? (
            <ul>
              {state.options.map((o) => (
                <li key={o.href}>
                  <Link href={o.href}>{o.label}</Link>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {state.injection ? (
        <p className="muted">The question seemed to give the system instructions; they were ignored.</p>
      ) : null}
    </form>
  );
}

const FIELD_NAMES = Object.keys(FIELDS) as FieldName[];

/** The filter as editable chips. Applying runs it again with no model call. */
export function ChipsEditor({ filter }: { filter: Filter }) {
  const router = useRouter();
  const [conditions, setConditions] = useState<Condition[]>(filter.conditions);
  const [sort, setSort] = useState<Filter["sort"]>(filter.sort);
  const [errors, setErrors] = useState<string[]>([]);
  const [newField, setNewField] = useState<FieldName>("due_date");
  const [newOp, setNewOp] = useState<Op>("on");
  const [newText, setNewText] = useState("");

  function apply(next: Condition[], nextSort = sort) {
    router.push(`/search?f=${encodeFilter({ conditions: next, sort: nextSort })}`);
  }

  function edit(i: number, text: string) {
    const c = conditions[i]!;
    const parsed = parseValue(c.field, c.op, text);
    if (!parsed.ok) {
      setErrors([parsed.error]);
      return;
    }
    setErrors([]);
    setConditions(conditions.map((x, j) => (j === i ? { ...x, value: parsed.value } : x)));
  }

  function add() {
    const parsed = parseValue(newField, newOp, newText);
    if (!parsed.ok) {
      setErrors([parsed.error]);
      return;
    }
    setErrors([]);
    const next = [...conditions, { field: newField, op: newOp, value: parsed.value }];
    setConditions(next);
    setNewText("");
    apply(next);
  }

  return (
    <section aria-labelledby="chips-heading" className="chips">
      <h2 id="chips-heading">Filter</h2>
      {errors.length > 0 ? (
        <p role="alert" className="error-box">
          {errors.join(" ")}
        </p>
      ) : null}
      {conditions.length === 0 ? <p className="muted">No conditions: every job you may see.</p> : null}
      <ul className="chip-list">
        {conditions.map((c, i) => (
          <li key={`${c.field}-${c.op}-${i}`} className="chip">
            <span>{chipLabel(c)}</span>
            {FIELDS[c.field].kind === "bool" ? (
              <button type="button" className="link-button" onClick={() => apply(conditions.map((x, j) => (j === i ? { ...x, value: !x.value } : x)))}>
                Switch
              </button>
            ) : FIELDS[c.field].kind === "true" ? null : (
              <input
                aria-label={`Edit ${FIELDS[c.field].label}`}
                defaultValue={valueText(c)}
                onBlur={(e) => edit(i, e.currentTarget.value)}
              />
            )}
            <button type="button" className="link-button" onClick={() => apply(conditions.filter((_, j) => j !== i))}>
              Remove {FIELDS[c.field].label}
            </button>
          </li>
        ))}
      </ul>
      <div className="inline-form" role="group" aria-label="Add a condition">
        <label>
          Field
          <select
            value={newField}
            onChange={(e) => {
              const f = e.currentTarget.value as FieldName;
              setNewField(f);
              setNewOp(FIELDS[f].ops[0]!);
            }}
          >
            {FIELD_NAMES.map((f) => (
              <option key={f} value={f}>
                {FIELDS[f].label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Operator
          <select value={newOp} onChange={(e) => setNewOp(e.currentTarget.value as Op)}>
            {FIELDS[newField].ops.map((op) => (
              <option key={op} value={op}>
                {OP_LABELS[op]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Value
          <input value={newText} onChange={(e) => setNewText(e.currentTarget.value)} placeholder="e.g. 2026-10-30, true, PLA-BLACK" />
        </label>
        <button type="button" className="button-secondary" onClick={add}>
          Add condition
        </button>
      </div>
      <div className="actions">
        <label>
          Sort
          <select
            value={sort}
            onChange={(e) => {
              const s = e.currentTarget.value as Filter["sort"];
              setSort(s);
            }}
          >
            <option value="due_date">Soonest due first</option>
            <option value="created">Newest first</option>
          </select>
        </label>
        <button type="button" onClick={() => apply(conditions)}>
          Run filter (no AI)
        </button>
      </div>
    </section>
  );
}
