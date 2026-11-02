import type { ReactNode } from "react";

/** Stat cards: a label and a number computed by code (never counted up, never estimated). */
export function Stats({ label, items }: { label: string; items: [string, ReactNode][] }) {
  return (
    <dl className="stats" aria-label={label}>
      {items.map(([name, value]) => (
        <div className="stat" key={name}>
          <dt className="stat-label">{name}</dt>
          <dd className="stat-value">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const GLYPH: Record<string, string> = {
  done: "✓",
  cancelled: "×",
  failed: "!",
  running: "▶",
  in_progress: "▶",
  in_production: "▶",
  planned: "◷",
  open: "○",
  pending: "○",
};

const TONE: Record<string, string> = {
  done: "ok",
  cancelled: "bad",
  failed: "bad",
  running: "active",
  in_progress: "active",
  in_production: "active",
};

/** A status in a pill: a symbol and the word, so it never relies on colour alone. Keyed by the
    status, so a change shows as the pill fading in anew. */
export function StatusPill({ status }: { status: string }) {
  return (
    <span key={status} className={`state state-${TONE[status] ?? "neutral"}`}>
      <span aria-hidden="true">{GLYPH[status] ?? "•"}</span> {status.replaceAll("_", " ")}
    </span>
  );
}
