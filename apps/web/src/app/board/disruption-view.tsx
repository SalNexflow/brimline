import type { Disruption, DisruptionCatalog, DisruptionEvent, Schedule } from "@/lib/engine";
import { EVENT_LABELS, type EventType } from "@/lib/disruption-form";
import { formatShopTime } from "@/lib/timeline";

import { DismissButton, EventEditor } from "./disruption-forms";

export function describeEvent(e: DisruptionEvent, timeZone: string): string {
  const at = (v: string | null | undefined, none: string) => (v ? formatShopTime(v, timeZone) : none);
  switch (e.type) {
    case "machine_down":
      return `${e.machine} down from ${at(e.starts_at, "when reported")} until ${at(e.ends_at, "further notice")}`;
    case "material_delayed":
      return `${e.material} not available until ${at(e.ends_at, "?")}`;
    case "rush_job":
      return `${e.order} becomes a rush order`;
    case "cancellation":
      return `${e.order}${e.line ? ` line ${e.line}` : " (whole order)"} cancelled`;
    default:
      return `The print on ${e.machine} will be done at ${at(e.ends_at, "?")}`;
  }
}

function Warnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div role="alert" className="warning-box">
      <strong>Check before you go on:</strong>
      <ul>
        {warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

/** One disruption: how it was understood (to check and confirm), or confirmed and waiting. */
export function DisruptionCard({
  d,
  catalog,
  timeZone,
}: {
  d: Disruption;
  catalog: DisruptionCatalog;
  timeZone: string;
}) {
  return (
    <article id={`disruption-${d.id}`} className="disruption" aria-labelledby={`disruption-${d.id}-title`}>
      <h3 id={`disruption-${d.id}-title`}>
        {d.status === "review" ? "Check how this was understood" : "Confirmed, waiting for a new plan"}
      </h3>
      {d.message ? (
        <blockquote className="message">{d.message}</blockquote>
      ) : (
        <p className="muted">Entered by hand.</p>
      )}
      <Warnings warnings={d.warnings} />
      {d.status === "review" ? (
        <>
          {d.issues.length > 0 ? (
            <div className="notice">
              <p>
                <strong>To settle before confirming:</strong>
              </p>
              <ul>
                {d.issues.map((i) => (
                  <li key={i}>{i}</li>
                ))}
              </ul>
              {d.question ? <p>{d.question}</p> : null}
            </div>
          ) : null}
          {d.notes.length > 0 ? (
            <ul className="muted">
              {d.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
          <p className="muted">
            {d.read_by === "model"
              ? "Read by the AI; times worked out by Brimline's own code. Correct anything that is wrong."
              : "Not read automatically: enter the events."}
          </p>
          <EventEditor
            disruptionId={d.id}
            events={d.events}
            choices={Object.fromEntries(
              Object.entries(d.choices).map(([k, v]) => [k, v.map(String)]),
            )}
            catalog={catalog}
            timeZone={timeZone}
            idempotencyKey={crypto.randomUUID()}
            submitLabel="Confirm these events"
          />
        </>
      ) : (
        <ul>
          {d.events.map((e, i) => (
            <li key={i}>
              {EVENT_LABELS[e.type as EventType]}: {describeEvent(e, timeZone)}
            </li>
          ))}
        </ul>
      )}
      <DismissButton disruptionId={d.id} idempotencyKey={crypto.randomUUID()} />
    </article>
  );
}

/** What a re-plan changes: computed by code; the summary is written from this only. */
export function DiffView({ schedule }: { schedule: Schedule }) {
  const diff = schedule.diff as Record<string, unknown> | null;
  const summary = schedule.summary as { text: string; highlights: string[]; source: string } | null;
  if (!diff || !diff.compared) return null; // a first plan: nothing to compare against
  const totals = diff.totals as Record<string, number | null>;
  const moved = diff.moved as {
    job: string;
    part: string;
    before: { machine: string; start: string; finish: string };
    after: { machine: string; start: string; finish: string };
    late_minutes_before: number;
    late_minutes_after: number;
  }[];
  const list = (key: string) => (diff[key] as { job: string; machine?: string }[] | undefined) ?? [];
  const notes = (diff.notes as string[] | undefined) ?? [];
  const warnings = (diff.warnings as string[] | undefined) ?? [];
  const events = (diff.events as string[] | undefined) ?? [];
  return (
    <section className="diff" aria-labelledby={`diff-${schedule.version}`}>
      <h3 id={`diff-${schedule.version}`}>What changes against the approved plan</h3>
      <Warnings warnings={warnings} />
      {events.length > 0 ? (
        <p>
          <strong>Disruptions included:</strong> {events.join("; ")}.
        </p>
      ) : null}
      {summary ? (
        <div className="summary">
          <p className="summary-source">
            {summary.source === "ai"
              ? "Summary written by AI from the change list below, and checked against it:"
              : "Summary written by Brimline from the change list below:"}
          </p>
          <p>{summary.text}</p>
          {summary.highlights.length > 0 ? (
            <ul>
              {summary.highlights.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <dl className="facts">
        <dt>Jobs moved</dt>
        <dd>
          {totals.jobs_moved} of {totals.jobs_planned}
        </dd>
        {totals.late_before !== null ? (
          <>
            <dt>Late jobs</dt>
            <dd>
              {totals.late_before} before, {totals.late_after} after
            </dd>
            <dt>Total lateness</dt>
            <dd>
              {totals.lateness_minutes_before} min before, {totals.lateness_minutes_after} min after
            </dd>
          </>
        ) : null}
      </dl>
      {notes.length > 0 ? (
        <ul className="notice">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      {list("lost_prints").length > 0 ? (
        <p>
          <strong>Prints lost and started again:</strong> {list("lost_prints").map((x) => `${x.job} on ${x.machine}`).join(", ")}
        </p>
      ) : null}
      {list("cancelled").length > 0 ? (
        <p>
          <strong>Cancelled:</strong> {list("cancelled").map((x) => x.job).join(", ")}
        </p>
      ) : null}
      {moved.length > 0 ? (
        <div className="table-scroll" role="region" aria-label="Jobs that move" tabIndex={0}>
          <table>
            <caption>Jobs that move (machine run)</caption>
            <thead>
              <tr>
                <th scope="col">Job</th>
                <th scope="col">Before</th>
                <th scope="col">After</th>
                <th scope="col">Late (min) before → after</th>
              </tr>
            </thead>
            <tbody>
              {moved.map((m) => (
                <tr key={m.job}>
                  <td>
                    {m.job} {m.part}
                  </td>
                  <td>
                    {m.before.machine}, {m.before.start}
                  </td>
                  <td>
                    {m.after.machine}, {m.after.start}
                  </td>
                  <td>
                    {m.late_minutes_before} → {m.late_minutes_after}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>No planned job moves.</p>
      )}
    </section>
  );
}
