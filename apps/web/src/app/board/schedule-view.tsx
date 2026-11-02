import Link from "next/link";
import type { CSSProperties } from "react";

import type { BoardJob, BoardTask, Schedule } from "@/lib/engine";
import { splitJobKey } from "@/lib/file-upload";
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

/** "days": the first few days, readable bars (the default); "all": the whole plan, narrower days. */
export type Span = "days" | "all";
export const SHOWN_DAYS = 3;

type Props = { schedule: Schedule; timeZone: string; now: Date; canAttach?: boolean; span?: Span };

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
        Re-checked just now by the independent checker, which shares no code with the scheduler:
        it reads the saved plan and the shop&apos;s config and applies every rule itself.
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
  const figures: [string, string][] = [
    ["Jobs planned", String(m("scheduled"))],
    ["Late or unscheduled", String(m("late_or_unscheduled"))],
    ["Total lateness", formatDuration(m("total_lateness_minutes"))],
    ["Material changeovers", String(m("changeovers"))],
  ];
  return (
    <dl className="stats metrics" aria-label="Plan figures, computed by the checker">
      {figures.map(([label, value]) => (
        <div className="stat" key={label}>
          <dt className="stat-label">{label}</dt>
          <dd className="stat-value">{value}</dd>
        </div>
      ))}
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

/** Bars per machine over time, plus rows for manual work (several people can work at once). By
    default only the first days are drawn, wide enough to read; work after them is marked per row,
    and the table below lists everything. */
export function Timeline({ schedule, timeZone, now, span = "days" }: Props) {
  const start = new Date(schedule.plan_start);
  const ends = schedule.tasks.map((t) => new Date(t.end));
  const w = boardWindow(start, ends, timeZone, SHOWN_DAYS, span === "all" ? Infinity : SHOWN_DAYS);
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
  const lastDay = formatShopDay(w.days.at(-1) ?? w.from, timeZone);

  return (
    <div
      className={`timeline timeline-${span}`}
      role="region"
      aria-label="Plan timeline (scrolls sideways)"
      tabIndex={0}
      id={`timeline-${schedule.version}`}
    >
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
        {rows.map((row, rowIndex) => (
          <div className="timeline-row" key={row.key} style={{ "--row": rowIndex } as CSSProperties}>
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
              {row.tasks.filter((t) => new Date(t.start) < w.to).map((t) => {
                const job = jobs.get(t.job);
                const left = percentAt(new Date(t.start), w);
                const width = Math.max(0.15, percentAt(new Date(t.end), w) - left);
                const barStyle = {
                  left: `${left}%`,
                  width: `${width}%`,
                  "--bar-color": t.machine ? materialToken(job?.material_code ?? "", materials) : "var(--bar-manual)",
                } as CSSProperties;
                const label = barLabel(t, job, timeZone);
                return (
                  <a
                    key={`${t.job}-${t.kind}`}
                    href={`#${taskAnchor(t, schedule.version)}`}
                    className={`bar bar-${t.machine ? "machine" : "manual"} bar-${t.status}${job?.rush ? " bar-rush" : ""}${new Date(t.end) > w.to ? " bar-continues" : ""}`}
                    style={barStyle}
                    aria-label={label}
                    data-tip={label}
                  >
                    <span className="bar-text">{barText(t, job)}</span>
                  </a>
                );
              })}
              <LaterMarker row={row} to={w.to} lastDay={lastDay} version={schedule.version} />
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

/** Work on this row that starts after the drawn days: a marker that points to the table. */
function LaterMarker({ row, to, lastDay, version }: { row: { key: string; label: string; tasks: BoardTask[] }; to: Date; lastDay: string; version: number }) {
  const later = row.tasks.filter((t) => new Date(t.start) >= to).length;
  if (later === 0) return null;
  return (
    <a
      className="later"
      href={`#table-${version}`}
      aria-label={`+${later} later: ${later} more ${later === 1 ? "task" : "tasks"} on ${row.label} after ${lastDay}, listed in the table`}
      data-testid={`later-${row.key}`}
    >
      +{later} later
    </a>
  );
}

/** Choose how much of the plan the timeline draws. Links, so it works without script and by keyboard. */
function SpanSwitch({ span, days, version }: { span: Span; days: number; version: number }) {
  if (days <= SHOWN_DAYS) return null;
  const option = (value: Span, text: string) => (
    <Link
      href={value === "days" ? `/board#timeline-${version}` : `/board?span=all#timeline-${version}`}
      className="segment"
      aria-current={span === value ? "true" : undefined}
      scroll={false}
    >
      {text}
    </Link>
  );
  return (
    <nav className="segmented" aria-label="Timeline span">
      {option("days", `First ${SHOWN_DAYS} days`)}
      {option("all", `Whole plan (${days} days)`)}
    </nav>
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
                    {t.kind === "machine" && job.grams_per_part ? (
                      <span className="muted">
                        {" "}
                        · {job.grams_per_part} g per part{job.grams_source ? ` (${job.grams_source})` : ""}
                      </span>
                    ) : null}
                    {job.material_short && t.kind === "machine" ? (
                      <Link href="/materials" className="badge badge-rush" data-testid={`waits-${job.key}`}>
                        waits for {job.material_code}
                      </Link>
                    ) : null}
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

export function NotPlanned({ schedule, canAttach = false }: { schedule: Schedule; canAttach?: boolean }) {
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
                <AttachLink job={u.job} show={canAttach && u.missing.includes("part size")} />
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
                {j.material_short ? (
                  <>
                    {" "}
                    (not enough {j.material_code}: <Link href="/materials">see Materials</Link>)
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

/** A file measured by code gives a job its part size; then plan again. */
function AttachLink({ job, show }: { job: string; show: boolean }) {
  const target = splitJobKey(job);
  if (!show || !target) return null;
  return (
    <>
      {" "}
      <Link href={`/files/new?order=${target.order}&line=${target.line}`}>Attach a model file</Link>
    </>
  );
}

export function ScheduleView({ schedule, timeZone, now, canAttach, span = "days" }: Props) {
  const ends = schedule.tasks.map((t) => new Date(t.end));
  const allDays = boardWindow(new Date(schedule.plan_start), ends, timeZone, SHOWN_DAYS).days.length;
  return (
    <>
      <CheckBadge schedule={schedule} />
      <Metrics schedule={schedule} />
      <NotPlanned schedule={schedule} canAttach={canAttach} />
      <SpanSwitch span={span} days={allDays} version={schedule.version} />
      <Timeline schedule={schedule} timeZone={timeZone} now={now} span={span} />
      <h3 id={`table-${schedule.version}`}>Plan as a table</h3>
      <div className="table-scroll" role="region" aria-labelledby={`table-${schedule.version}`} tabIndex={0}>
        <PlanTable schedule={schedule} timeZone={timeZone} />
      </div>
    </>
  );
}
