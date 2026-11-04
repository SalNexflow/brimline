import type { ReactNode } from "react";

import type { ConnectivityView } from "@/lib/engine";
import { formatShopTime } from "@/lib/timeline";

export type MachineConnectivity = ConnectivityView["machines"][number];
type HistoryItem = MachineConnectivity["history"][number];

// Every state is a symbol and a word, so it never relies on colour alone (D190).
type Look = { word: string; glyph: string; tone: string };
const NO_DATA: Look = { word: "No data yet", glyph: "?", tone: "neutral" };
const STATE: Record<string, Look> = {
  connected: { word: "Connected", glyph: "✓", tone: "ok" },
  slow: { word: "Slow", glyph: "◔", tone: "warn" },
  unreachable: { word: "Unreachable", glyph: "×", tone: "bad" },
  no_data: NO_DATA,
};

export const SIM_MODE: Record<string, string> = {
  success: "works normally",
  slow: "answers slowly",
  unresponsive: "stops answering",
  failure: "refuses to start",
};

/** The connection state in a pill. Keyed by state, so a change fades in anew (reduced motion: none). */
export function ConnectionPill({ state }: { state: string }) {
  const s = STATE[state] ?? NO_DATA;
  return (
    <span key={state} className={`state state-${s.tone}`} data-testid="connection-state">
      <span aria-hidden="true">{s.glyph}</span> {s.word}
    </span>
  );
}

export function connectionWord(state: string): string {
  return (STATE[state] ?? NO_DATA).word;
}

/** "12 s ago", from the engine's clock (both times come from the engine, so they agree). */
export function ago(at: string, now: string): string {
  const seconds = Math.max(0, Math.round((Date.parse(now) - Date.parse(at)) / 1000));
  if (seconds < 90) return `${seconds} s ago`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}

/** A local mock often answers within the millisecond; "0 ms" would read as no answer. */
export function milliseconds(ms: number | null | undefined): string {
  if (ms == null) return "–";
  return ms < 1 ? "under 1 ms" : `${ms} ms`;
}

function pollWord(h: HistoryItem): string {
  return !h.ok ? "no answer" : h.slow ? `slow, ${milliseconds(h.response_ms)}` : milliseconds(h.response_ms);
}

/** The recent polls, newest on the right. One accessible summary for the whole strip; each cell
    shows its own result on hover (a symbol too, not colour only). */
export function HistoryStrip({ history, code }: { history: HistoryItem[]; code: string }) {
  if (history.length === 0) return <p className="muted">No polls recorded yet.</p>;
  const answered = history.filter((h) => h.ok).length;
  const slow = history.filter((h) => h.ok && h.slow).length;
  const summary = `Last ${history.length} polls of ${code}, oldest first: ${answered - slow} answered, ${slow} slow, ${history.length - answered} no answer.`;
  return (
    <div className="poll-strip" role="img" aria-label={summary} data-testid="poll-strip">
      {[...history].reverse().map((h, i) => (
        <span
          key={`${h.at}-${i}`}
          className={`poll poll-${!h.ok ? "fail" : h.slow ? "slow" : "ok"}`}
          title={`${h.source === "test" ? "Test" : "Poll"}: ${pollWord(h)}`}
        >
          {!h.ok ? "×" : h.slow ? "◔" : ""}
        </span>
      ))}
    </div>
  );
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** One machine's card. Text the machine sent, and errors, are shown as quoted text: React escapes
    it, and nothing on this page acts on it. */
export function MachineCard({
  m,
  now,
  timeZone,
  uptimeMinutes = 60,
  actions,
}: {
  m: MachineConnectivity;
  now: string;
  timeZone: string;
  uptimeMinutes?: number;
  actions?: ReactNode;
}) {
  const period = uptimeMinutes === 60 ? "last hour" : `last ${uptimeMinutes} min`;
  const uptime =
    m.taken === 0 ? `no polls in the ${period}` : `${Math.round((100 * m.answered) / m.taken)} % of ${m.taken} ${m.taken === 1 ? "poll" : "polls"}`;
  return (
    <li className="card connectivity-card" id={`machine-${m.code}`} data-testid={`connectivity-${m.code}`}>
      <h3>
        {m.code} <ConnectionPill state={m.state} />
      </h3>
      <p>
        {m.protocol} <span className="badge">simulated</span>
        {m.source === "community" ? <span className="badge badge-rush">community-documented protocol</span> : null}
      </p>
      <dl className="facts conn-facts">
        <Fact term="Last answer">
          {m.last_ok_at ? (
            <time dateTime={m.last_ok_at} title={formatShopTime(m.last_ok_at, timeZone)}>
              {ago(m.last_ok_at, now)}
            </time>
          ) : (
            "none recorded"
          )}
        </Fact>
        <Fact term="Response time">{milliseconds(m.last_response_ms)}</Fact>
        <Fact term={`Uptime, ${period}`}>{uptime}</Fact>
        <Fact term="Simulator">{SIM_MODE[m.simulated_mode] ?? m.simulated_mode}</Fact>
      </dl>
      {m.fault ? (
        <p className="fault" data-testid="fault">
          <strong>Fault:</strong> {m.fault}
        </p>
      ) : null}
      {m.machine_says ? (
        <p className="muted" data-testid="machine-says">
          Machine says: <q>{m.machine_says}</q>
        </p>
      ) : null}
      {m.last_error ? (
        <p className="muted" data-testid="last-error">
          Last error{m.last_error_at ? ` (${ago(m.last_error_at, now)})` : ""}: <q>{m.last_error}</q>
        </p>
      ) : null}
      <HistoryStrip history={m.history} code={m.code} />
      {actions}
    </li>
  );
}
