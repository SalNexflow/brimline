import type { Metadata } from "next";
import { Suspense } from "react";

import { signedInEngine, type QueueTask } from "@/lib/engine";
import { kindLabel, statusLabel } from "@/lib/task-labels";
import { formatShopTime } from "@/lib/timeline";

import { TaskActions } from "./task-actions";

export const metadata: Metadata = { title: "Queues · Brimline" };

function describe(t: QueueTask): string {
  return `${kindLabel(t.kind)} for ${t.order_number} ${t.part_name}`;
}

function TaskRow({ t, timeZone, canUpdate }: { t: QueueTask; timeZone: string; canUpdate: boolean }) {
  const actions = t.status === "running" ? (["done", "fail"] as const) : t.can_start ? (["start"] as const) : [];
  return (
    <tr data-testid={`task-${t.job}-${t.kind}`}>
      <td data-label="Planned start">{formatShopTime(t.planned_start, timeZone)}</td>
      <td data-label="Job">
        {t.order_number} {t.part_name}, {t.quantity} × {t.material_code}
        {t.rush ? <span className="badge badge-rush">rush</span> : null}
      </td>
      <td data-label="Task">{kindLabel(t.kind)}</td>
      <td data-label="Status">
        {statusLabel(t.status)}
        {t.actual_start && t.status === "running" ? (
          <span className="muted"> since {formatShopTime(t.actual_start, timeZone)}</span>
        ) : null}
        {t.waiting_for ? <span className="muted"> ({t.waiting_for})</span> : null}
      </td>
      <td data-label="Actions">
        {canUpdate && actions.length > 0 ? (
          <TaskActions
            taskId={t.id}
            label={describe(t)}
            actions={[...actions]}
            keys={{ start: crypto.randomUUID(), done: crypto.randomUUID(), fail: crypto.randomUUID() }}
          />
        ) : null}
      </td>
    </tr>
  );
}

export default function QueuesPage() {
  return (
    <main className="page">
      <h1 className="page-title">Queues</h1>
      <Suspense fallback={<p>Loading the queues…</p>}>
        <QueuesContent />
      </Suspense>
    </main>
  );
}

async function QueuesContent() {
  const { client } = await signedInEngine();
  const { data } = await client.GET("/queues");
  if (!data) return <p>You do not have access to the queues.</p>;
  const tz = data.time_zone;
  return (
    <>
      {data.schedule_version === null ? (
        <p>No approved plan yet. Work appears here once a planner approves a plan.</p>
      ) : (
        <p className="muted">From the approved plan, version {data.schedule_version}. Times are {tz} time.</p>
      )}
      {data.queues
        .filter((q) => q.tasks.length > 0)
        .map((q) => {
          const open = q.tasks.filter((t) => t.status === "planned" || t.status === "running");
          const finished = q.tasks.filter((t) => t.status === "done" || t.status === "failed");
          const headingId = `queue-${q.machine ?? "manual"}`;
          return (
            <section key={headingId} aria-labelledby={headingId} className="queue queue-stacked">
              <h2 id={headingId}>{q.machine ? `${q.machine}: ${q.name}` : q.name}</h2>
              <div className="table-scroll" role="region" aria-labelledby={headingId} tabIndex={0}>
              <table>
                <caption className="visually-hidden">Next tasks for {q.name}</caption>
                <thead>
                  <tr>
                    <th scope="col">Planned start</th>
                    <th scope="col">Job</th>
                    <th scope="col">Task</th>
                    <th scope="col">Status</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {open.map((t) => (
                    <TaskRow key={t.id} t={t} timeZone={tz} canUpdate={data.can_update} />
                  ))}
                </tbody>
              </table>
              </div>
              {finished.length > 0 ? (
                <details>
                  <summary>Finished ({finished.length})</summary>
                  <ul>
                    {finished.map((t) => (
                      <li key={t.id} data-testid={`task-${t.job}-${t.kind}`}>
                        {describe(t)}: {statusLabel(t.status)}
                        {t.actual_end ? ` at ${formatShopTime(t.actual_end, tz)}` : ""}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </section>
          );
        })}
    </>
  );
}
