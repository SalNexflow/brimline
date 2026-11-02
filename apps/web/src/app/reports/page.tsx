import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { signedInEngine, type CostReport } from "@/lib/engine";
import { formatMoney } from "@/lib/money";
import { formatDuration } from "@/lib/timeline";
import { FAILURE_REASONS, type FailureReason } from "@/lib/task-mark";

import { Stats } from "../ui";

export const metadata: Metadata = { title: "Reports · Brimline" };

/** A ratio from the engine as "+33 %" (display only; the engine computed it). */
function overrun(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "—";
  const pct = Math.round((ratio - 1) * 100);
  return `${pct > 0 ? "+" : ""}${pct} %`;
}

// Set by code, never picked by an operator: a print lost to a breakdown, work stopped by a cancellation.
const SYSTEM_REASONS: Record<string, string> = { machine_down: "Machine went down", order_cancelled: "Order cancelled" };

function reasonText(reason: string): string {
  return FAILURE_REASONS[reason as FailureReason] ?? SYSTEM_REASONS[reason] ?? reason;
}

export default function ReportsPage() {
  return (
    <main className="page">
      <h1 className="page-title">Quoted versus actual</h1>
      <Suspense fallback={<p>Loading the report…</p>}>
        <ReportContent />
      </Suspense>
    </main>
  );
}

async function ReportContent() {
  const { client } = await signedInEngine();
  const { data: report, response } = await client.GET("/reports/quoted-vs-actual");
  if (response.status === 403 || !report) {
    return <p role="status">Your role does not see the shop&apos;s reports.</p>;
  }
  const flagged = report.types.filter((t) => t.flagged);
  return (
    <>
      <p className="lede">What every finished job really used, against its quote. Computed by code; no AI.</p>
      <details className="how">
        <summary>How this works</summary>
        <p>
          Both sides are priced with the quote&apos;s own price rules, so a later price change does not count as an
          overrun. Failed attempts and reprints are the shop&apos;s cost and count in the actual. Times and grams are the
          recorded ones.
        </p>
      </details>
      <Stats
        label="Finished jobs and flags, counted by code"
        items={[
          ["Finished jobs", report.jobs.length],
          ["With a quote", report.jobs.length - report.not_quoted_jobs],
          ["Failed attempts", report.types.reduce((n, t) => n + t.failed_attempts, 0)],
          ["Flagged for review", flagged.length],
        ]}
      />
      {report.synthetic_jobs > 0 ? (
        <p role="note" className="notice" data-testid="synthetic-note">
          <strong>Synthetic history:</strong> {report.synthetic_jobs} of these jobs are made-up history seeded for the demo
          (marked <span className="badge">synthetic</span> below), so the report has something to find. One material in
          it is under-quoted on purpose.
        </p>
      ) : null}
      <h2>Job types to review</h2>
      <p className="muted lede">
        A material is flagged when at least {report.min_jobs} quoted jobs have finished and more of them cost over{" "}
        {overrun(report.threshold_ratio)} of their quote than chance explains (sign test, chance under {report.alpha}).
        The report only suggests; prices change only when someone adds a new price version.
      </p>
      {flagged.length === 0 ? (
        <p role="status" className="lede">
          Nothing is flagged.
        </p>
      ) : (
        <ul className="flag-list shortage-list">
          {flagged.map((t) => (
            <li key={t.material_code} className="card shortage" data-testid={`flag-${t.material_code}`}>
              <span className="state state-bad">
                <span aria-hidden="true">!</span> review
              </span>{" "}
              <strong>{t.material_code}</strong> ({t.process}): {t.reason}{" "}
              <Link href="/price-rules">{t.suggestion}</Link>
            </li>
          ))}
        </ul>
      )}
      <TypesTable report={report} />
      <JobsTable report={report} />
    </>
  );
}

function TypesTable({ report }: { report: CostReport }) {
  return (
    <>
      <h2 id="types-heading">By job type</h2>
      <div className="table-scroll" role="region" aria-labelledby="types-heading" tabIndex={0}>
        <table>
          <caption className="visually-hidden">Quoted versus actual per material</caption>
          <thead>
            <tr>
              <th scope="col">Material</th>
              <th scope="col" className="num">Finished (quoted)</th>
              <th scope="col" className="num">Over {overrun(report.threshold_ratio)}</th>
              <th scope="col" className="num">Median cost vs quote</th>
              <th scope="col" className="num">Median machine time vs quote</th>
              <th scope="col" className="num">Failed attempts</th>
              <th scope="col">Flag</th>
            </tr>
          </thead>
          <tbody>
            {report.types.map((t) => (
              <tr key={t.material_code}>
                <td data-label="Material">{t.material_code}</td>
                <td data-label="Finished (quoted)" className="num">
                  {t.jobs} ({t.quoted_jobs})
                </td>
                <td data-label="Over threshold" className="num">
                  {t.over_threshold} of {t.quoted_jobs}
                </td>
                <td data-label="Median cost vs quote" className="num">{overrun(t.median_cost_ratio)}</td>
                <td data-label="Median machine time vs quote" className="num">{overrun(t.median_time_ratio)}</td>
                <td data-label="Failed attempts" className="num">
                  {t.failed_attempts} of {t.attempts}
                </td>
                <td data-label="Flag" title={t.reason}>
                  {t.flagged ? (
                    <span className="state state-bad">
                      <span aria-hidden="true">!</span> Review
                    </span>
                  ) : (
                    <span className="muted">{t.quoted_jobs < report.min_jobs ? "Too few" : "No"}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function JobsTable({ report }: { report: CostReport }) {
  const money = (cents: number | null | undefined) => (cents === null || cents === undefined ? "—" : formatMoney(cents, report.currency));
  return (
    <>
      <h2 id="jobs-heading">Finished jobs, newest first</h2>
      {report.not_quoted_jobs > 0 ? (
        <p className="muted lede">{report.not_quoted_jobs} job(s) had no quote: their time is compared with the plan, their cost is not.</p>
      ) : null}
      <div className="table-scroll" role="region" aria-labelledby="jobs-heading" tabIndex={0}>
        <table>
          <caption className="visually-hidden">Each finished job against its quote</caption>
          <thead>
            <tr>
              <th scope="col">Job</th>
              <th scope="col">Material</th>
              <th scope="col" className="num">Quoted cost</th>
              <th scope="col" className="num">Actual cost</th>
              <th scope="col" className="num">Difference</th>
              <th scope="col" className="num">Machine time, quoted / actual</th>
              <th scope="col" className="num">Attempts</th>
            </tr>
          </thead>
          <tbody>
            {report.jobs.map((j, i) => (
              <tr key={`${j.label}-${i}`}>
                <td data-label="Job">
                  {j.label} {j.synthetic ? <span className="badge">synthetic</span> : null}
                </td>
                <td data-label="Material">{j.material_code}</td>
                <td data-label="Quoted cost" className="num">{money(j.estimated_cents)}</td>
                <td data-label="Actual cost" className="num">
                  {money(j.actual_cents)}
                  {j.grams_assumed > 0 ? <span className="muted"> (grams assumed for {j.grams_assumed})</span> : null}
                </td>
                <td data-label="Difference" className="num">{overrun(j.cost_ratio)}</td>
                <td data-label="Machine time" className="num">
                  {formatDuration(j.estimated_minutes)} / {formatDuration(Math.round(j.actual_minutes))}
                </td>
                <td data-label="Attempts" className="num">
                  {j.attempts}
                  {j.failure_reasons.length > 0 ? <span className="muted"> ({j.failure_reasons.map(reasonText).join(", ")})</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
