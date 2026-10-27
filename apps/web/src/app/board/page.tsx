import type { Metadata } from "next";
import { Suspense } from "react";

import { signedInEngine, type PlanningRun, type Schedule } from "@/lib/engine";
import { formatShopTime } from "@/lib/timeline";

import { AutoRefresh, DecisionForm, PlanDayForm } from "./forms";
import { ScheduleView } from "./schedule-view";

export const metadata: Metadata = { title: "Board · Brimline" };

const PHASES: Record<string, string> = {
  queued: "Waiting to start",
  building: "Collecting jobs and machines",
  solving: "Searching for the best plan",
  checking: "Independent check of the plan",
  done: "Done",
  failed: "Failed",
};

function RunProgress({ run, now }: { run: PlanningRun; now: Date }) {
  const active = run.status === "queued" || run.status === "running";
  const p = run.progress as Record<string, number | boolean | undefined>;
  const elapsed = run.started_at ? Math.max(0, Math.round((now.getTime() - new Date(run.started_at).getTime()) / 1000)) : 0;
  const work = typeof p.work_done === "number" ? p.work_done : undefined;
  if (!active && run.status !== "failed") return null;
  return (
    <div className="run-progress" role="status" aria-live="polite" data-testid="run-progress">
      {run.status === "failed" ? (
        <p className="error-box">Planning failed: {run.error}</p>
      ) : (
        <>
          <p>
            <strong>Planning:</strong> {PHASES[run.phase] ?? run.phase} ({elapsed} s)
            {typeof p.jobs === "number" ? `, ${p.jobs} jobs` : null}
          </p>
          <progress max={1} value={work} aria-label="Share of the solver's work budget used">
            {work === undefined ? "" : `${Math.round(work * 100)}%`}
          </progress>
          {typeof p.solutions === "number" ? (
            <p className="muted">
              Better plans found so far: {p.solutions}. The search stops at the quality limit (about 20 s of
              solver work), which can take longer in real time.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

function approveReason(s: Schedule): string | null {
  if (s.can_approve) return null;
  if (!s.check.valid) return "It cannot be approved: the independent check failed.";
  if (s.stale) return "It cannot be approved: jobs or work changed since it was made. Plan again.";
  return null;
}

function Header({ s, timeZone }: { s: Schedule; timeZone: string }) {
  return (
    <p className="muted">
      Version {s.version}, made by {s.created_by_name} on {formatShopTime(s.created_at, timeZone)}
      {s.decided_at && s.decided_by_name
        ? `; ${s.status} by ${s.decided_by_name} on ${formatShopTime(s.decided_at, timeZone)}`
        : ""}
      . Planned from {formatShopTime(s.plan_start, timeZone)} ({timeZone} time).
    </p>
  );
}

export default function BoardPage() {
  return (
    <main className="page board">
      <h1 className="page-title">Production board</h1>
      <Suspense fallback={<p>Loading the board…</p>}>
        <BoardContent />
      </Suspense>
    </main>
  );
}

async function BoardContent() {
  const { client } = await signedInEngine();
  const { data: board } = await client.GET("/board");
  const now = new Date();
  if (!board) return <p>You do not have access to the board.</p>;
  const tz = board.time_zone;
  const run = board.run;
  const busy = run !== null && (run.status === "queued" || run.status === "running");
  return (
    <>
      <AutoRefresh active={busy} />
      {board.can_plan ? <PlanDayForm idempotencyKey={crypto.randomUUID()} busy={busy} /> : null}
      {run ? <RunProgress run={run} now={now} /> : null}

      {board.draft ? (
        <section aria-labelledby="draft-heading" className="schedule">
          <h2 id="draft-heading">Draft plan, waiting for approval</h2>
          <Header s={board.draft} timeZone={tz} />
          {board.can_plan ? (
            <DecisionForm
              scheduleId={board.draft.id}
              approveKey={crypto.randomUUID()}
              discardKey={crypto.randomUUID()}
              canApprove={board.draft.can_approve}
              reason={approveReason(board.draft)}
            />
          ) : null}
          <ScheduleView schedule={board.draft} timeZone={tz} now={now} />
        </section>
      ) : null}

      {board.approved ? (
        <section aria-labelledby="approved-heading" className="schedule">
          <h2 id="approved-heading">Approved plan</h2>
          <Header s={board.approved} timeZone={tz} />
          <ScheduleView schedule={board.approved} timeZone={tz} now={now} />
        </section>
      ) : null}

      {!board.draft && !board.approved ? (
        <p>No plan yet. {board.can_plan ? "Press Plan day to make one." : "A planner makes one with Plan day."}</p>
      ) : null}
    </>
  );
}
