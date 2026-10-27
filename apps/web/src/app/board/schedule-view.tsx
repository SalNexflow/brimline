import type { CSSProperties } from "react";

import type { BoardJob, BoardTask, Schedule } from "@/lib/engine";
import { kindLabel, statusLabel } from "@/lib/task-labels";
import {
  boardWindow,
  formatDuration,
  formatShopDay,
  formatShopTime,
  lanes,
  materialToken,
  percentAt,
} from "@/lib/timeline";

type Props = { schedule: Schedule; timeZone: string; now: Date };

/** Row ids in the table; the version keeps a draft's and the approved plan's apart. */
function taskAnchor(t: BoardTask, version: number): string {
  return `v${version}-${t.job}-${t.kind}`;
}

/** The independent checker's verdict on the saved plan. Never the scheduler's own claim. */
export function CheckBadge({ schedule }: { schedule: Schedule }) {
  const { check } = schedule;
  return (
    <section
      className={`check ${check.valid ? "check-ok" : "check-fail"}`}
      aria-label="Independent check"
      data-testid="check-badge"
    >
      <p className="check-title">
        <span aria-hidden="true">{check.valid ? "✓" : "✗"}</span> Independent check:{" "}
        <strong>{check.valid ? "passed" : "failed"}</strong>
      </p>
      <p className="muted">
        The checker re-validated the saved plan from its raw inputs just now; it shares no code with
        the scheduler.
      </p>
      {check.violations.length > 0 ? (
        <>
          <p>
            {check.violations.length} rule {check.violations.length === 1 ? "violation" : "violations"}:
          </p>
          <ul className="violations">
            {check.violations.map((v, i) => (
              <li key={i}>
                <code>{v.code}</code> {v.job ? <strong>{v.job}</strong> : null} {v.detail}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {check.warnings.length > 0 ? (
        <details>
          <summary>
            {check.warnings.length} {check.warnings.length === 1 ? "warning" : "warnings"} (not rule violations)
          </summary>
          <ul>
            {check.warnings.map((w, i) => (
              <li key={i}>
                <strong>{w.job}</strong> was left unscheduled but looks like it could fit: {w.detail}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}

function Metrics({ schedule }: { schedule: Schedule }) {
  const metrics = schedule.check.metrics;
  if (!metrics) return null;
  const m = (name: string): number => metrics[name] ?? 0;
  return (
    <dl className="facts metrics" aria-label="Plan figures, computed by the checker">
      <dt>Jobs planned</dt>
      <dd>{m("scheduled")}</dd>
      <dt>Late or unscheduled</dt>
      <dd>{m("late_or_unscheduled")}</dd>
      <dt>Total lateness</dt>
      <dd>{formatDuration(m("total_lateness_minutes"))}</dd>
      <dt>Material changeovers</dt>
      <dd>{m("changeovers")}</dd>
    </dl>
  );
}

/** The short text drawn on a bar. */
function barText(t: BoardTask, job: BoardJob | undefined): string {
  return `${job?.order_number ?? t.job} ${t.machine ? (job?.material_code ?? "") : kindLabel(t.kind)}`;
}

/** The bar's full name for screen readers. It starts with the visible text (WCAG 2.5.3). */
function barLabel(t: BoardTask, job: BoardJob | undefined, timeZone: string): string {
  const where = t.machine ?? "manual work";
  const what = job ? `${job.part_name}, ${job.quantity} parts` : t.job;
  return `${barText(t, job)}: ${what}, ${kindLabel(t.kind)} on ${where}, ${formatShopTime(t.start, timeZone)} to ${formatShopTime(t.end, timeZone)}, ${statusLabel(t.status)}`;
}

/** Bars per machine over time, plus rows for manual work (several people can work at once). */
export function Timeline({ schedule, timeZone, now }: Props) {
  const start = new Date(schedule.plan_start);
  const ends = schedule.tasks.map((t) => new Date(t.end));
  const w = boardWindow(start, ends, timeZone);
  const jobs = new Map(schedule.jobs.map((j) => [j.key, j]));
  const materials = schedule.jobs.map((j) => j.material_code);
  const manual = schedule.tasks.filter((t) => t.machine === null);
  const manualLanes = lanes(manual.map((t) => ({ start: new Date(t.start), end: new Date(t.end) })));
  const laneCount = Math.max(1, ...manualLanes.map((l) => l + 1));
  const rows: { key: string; label: string; tasks: BoardTask[] }[] = [
    ...schedule.machines.map((m) => ({
      key: m.code,
      label: m.code,
      tasks: schedule.tasks.filter((t) => t.machine === m.code),
    })),
    ...Array.from({ length: laneCount }, (_, lane) => ({
      key: `manual-${lane}`,
      label: laneCount > 1 ? `Manual ${lane + 1}` : "Manual",
      tasks: manual.filter((_, i) => manualLanes[i] === lane),
    })),
  ];
  const nowInside = now >= w.from && now <= w.to;
  const style = { "--days": w.days.length } as CSSProperties;

  return (
    <div className="timeline" role="region" aria-label="Plan timeline (scrolls sideways)" tabIndex={0}>
      <div className="timeline-grid" style={style}>
        <div className="timeline-row timeline-head" aria-hidden="true">
          <div className="timeline-label" />
          <div className="timeline-track">
            {w.days.map((d) => (
              <span key={d.toISOString()} className="day-label" style={{ left: `${percentAt(d, w)}%` }}>
                {formatShopDay(d, timeZone)}
              </span>
            ))}
          </div>
        </div>
        {rows.map((row) => (
          <div className="timeline-row" key={row.key}>
            <div className="timeline-label">{row.label}</div>
            <div className="timeline-track">
              {schedule.shifts.map((s) => {
                const left = percentAt(new Date(s.start), w);
                const right = percentAt(new Date(s.end), w);
                return right > left ? (
                  <span key={s.start} className="shift-band" style={{ left: `${left}%`, width: `${right - left}%` }} />
                ) : null;
              })}
              {w.days.map((d) => (
                <span key={d.toISOString()} className="day-line" style={{ left: `${percentAt(d, w)}%` }} />
              ))}
              {row.tasks.map((t) => {
                const job = jobs.get(t.job);
                const left = percentAt(new Date(t.start), w);
                const width = Math.max(0.15, percentAt(new Date(t.end), w) - left);
                const barStyle = {
                  left: `${left}%`,
                  width: `${width}%`,
                  "--bar-color": t.machine ? materialToken(job?.material_code ?? "", materials) : "var(--bar-manual)",
                } as CSSProperties;
                return (
                  <a
                    key={`${t.job}-${t.kind}`}
                    href={`#${taskAnchor(t, schedule.version)}`}
                    className={`bar bar-${t.machine ? "machine" : "manual"} bar-${t.status}${job?.rush ? " bar-rush" : ""}`}
                    style={barStyle}
                    aria-label={barLabel(t, job, timeZone)}
                    title={barLabel(t, job, timeZone)}
                  >
                    <span className="bar-text">{barText(t, job)}</span>
                  </a>
                );
              })}
              {nowInside ? <span className="now-marker" style={{ left: `${percentAt(now, w)}%` }} aria-hidden="true" /> : null}
            </div>
          </div>
        ))}
      </div>
      <p className="visually-hidden">
        Now: {formatShopTime(now, timeZone)}. The plan starts {formatShopTime(schedule.plan_start, timeZone)}.
      </p>
    </div>
  );
}

/** The same plan as a table: the accessible, printable, searchable view of every task. */
export function PlanTable({ schedule, timeZone }: Omit<Props, "now">) {
  const jobs = new Map(schedule.jobs.map((j) => [j.key, j]));
  const tasks = [...schedule.tasks].sort((a, b) => a.start.localeCompare(b.start));
  return (
    <table className="plan-table">
      <caption>Every planned task, in time order (shop time)</caption>
      <thead>
        <tr>
          <th scope="col">Start</th>
          <th scope="col">End</th>
          <th scope="col">Where</th>
          <th scope="col">Task</th>
          <th scope="col">Job</th>
          <th scope="col">Due</th>
          <th scope="col">Status</th>
        </tr>
      </thead>
      <tbody>
        {tasks.map((t) => {
          const job = jobs.get(t.job);
          return (
            <tr key={taskAnchor(t, schedule.version)} id={taskAnchor(t, schedule.version)} tabIndex={-1}>
              <td>{formatShopTime(t.start, timeZone)}</td>
              <td>{formatShopTime(t.end, timeZone)}</td>
              <td>{t.machine ?? "Manual"}</td>
              <td>{kindLabel(t.kind)}</td>
              <td>
                {job ? (
                  <>
                    {job.order_number} {job.part_name}, {job.quantity} × {job.material_code}
                    {job.rush ? <span className="badge badge-rush">rush</span> : null}
                  </>
                ) : (
                  t.job
                )}
              </td>
              <td>
                {job ? formatShopTime(job.due, timeZone) : ""}
                {job && job.late_minutes > 0 && t.kind === "finish" ? (
                  <span className="late"> late by {formatDuration(job.late_minutes)}</span>
                ) : null}
              </td>
              <td>{statusLabel(t.status)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function NotPlanned({ schedule }: { schedule: Schedule }) {
  const unscheduled = schedule.jobs.filter((j) => j.unscheduled);
  if (schedule.unplannable.length === 0 && unscheduled.length === 0) return null;
  return (
    <div className="notice">
      {schedule.unplannable.length > 0 ? (
        <>
          <p>
            <strong>Cannot plan yet</strong> (information missing, never guessed):
          </p>
          <ul>
            {schedule.unplannable.map((u) => (
              <li key={u.job}>
                {u.job} {u.part}: missing {u.missing.join(", ")}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {unscheduled.length > 0 ? (
        <>
          <p>
            <strong>Did not fit</strong> in the planning horizon:
          </p>
          <ul>
            {unscheduled.map((j) => (
              <li key={j.key}>
                {j.order_number} {j.part_name}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

export function ScheduleView({ schedule, timeZone, now }: Props) {
  return (
    <>
      <CheckBadge schedule={schedule} />
      <Metrics schedule={schedule} />
      <NotPlanned schedule={schedule} />
      <Timeline schedule={schedule} timeZone={timeZone} now={now} />
      <h3 id={`table-${schedule.version}`}>Plan as a table</h3>
      <div className="table-scroll" role="region" aria-labelledby={`table-${schedule.version}`} tabIndex={0}>
        <PlanTable schedule={schedule} timeZone={timeZone} />
      </div>
    </>
  );
}
