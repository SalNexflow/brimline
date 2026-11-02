import type { Metadata } from "next";
import { Suspense } from "react";

import { can, signedInEngine, type DispatchView } from "@/lib/engine";

import { AskButton, ProceedForm, SimulationForm, type ProposalRow } from "./forms";

export const metadata: Metadata = { title: "Dispatch · Brimline" };

type Run = DispatchView["runs"][number];

const ACTION: Record<string, string> = { start_task: "Start", stop_task: "Stop" };
const STATE: Record<string, string> = {
  idle: "Idle",
  running: "Running",
  done: "Finished, ready",
  failed: "Failed",
  offline: "Offline",
};
// A symbol per state, so the state never relies on colour alone (the word is always there too).
const GLYPH: Record<string, string> = { idle: "○", running: "▶", done: "✓", failed: "!", offline: "×" };

export default function DispatchPage({ searchParams }: PageProps<"/dispatch">) {
  return (
    <main className="page">
      <h1 className="page-title">Dispatch</h1>
      <Suspense fallback={<p>Asking the machines…</p>}>
        <DispatchContent searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function DispatchContent({ searchParams }: { searchParams: PageProps<"/dispatch">["searchParams"] }) {
  const { client, me } = await signedInEngine();
  const { data, response } = await client.GET("/dispatch");
  if (response.status === 403 || !data) {
    return <p role="status">Your role does not dispatch work to machines.</p>;
  }
  const params = await searchParams;
  const notice = params.proceeded ? "Proceed recorded; the log below shows what each call did." : params.asked ? "The dispatcher made its proposals. Nothing has reached a machine yet." : params.simulated ? `Simulation of ${String(params.simulated)} changed.` : null;
  const mayAsk = can(me, "dispatch.ask");
  const mayProceed = can(me, "dispatch.proceed");
  const run = data.runs[0];
  return (
    <>
      <p role="note" className="notice" data-testid="simulated-notice">
        {data.simulated_notice}
      </p>
      {notice ? (
        <p role="status" className="toast">
          {notice}
        </p>
      ) : null}
      <p className="lede">An AI agent proposes which planned prints to start; nothing reaches a machine until a person presses Proceed.</p>
      <details className="how">
        <summary>How this works</summary>
        <p>
          A person approves specific proposals with Proceed; only then does the agent issue those actions as tool calls, and
          code checks every call against the approved plan, the machine&apos;s own state, the material in stock and the
          Proceed. When the agent cannot be used, code carries out exactly the approved actions and says so. Text from
          people and machines is shown as their words, never obeyed.
        </p>
      </details>
      {!data.connected ? <p role="status">No machines are connected (SIM_MACHINES is off).</p> : null}
      <dl className="stats" aria-label="Machines and proposals, counted by code">
        {[
          ["Machines", data.machines.length],
          ["Running", data.machines.filter((m) => m.state === "running").length],
          ["Idle", data.machines.filter((m) => m.state === "idle" || m.state === "done").length],
          ["Not answering", data.machines.filter((m) => !m.state || m.state === "offline" || m.state === "failed").length],
        ].map(([label, value]) => (
          <div className="stat" key={label}>
            <dt className="stat-label">{label}</dt>
            <dd className="stat-value">{value}</dd>
          </div>
        ))}
      </dl>
      <h2>Machines</h2>
      <ul className="machine-grid">
        {data.machines.map((m) => (
          <li key={m.code} className="card" data-testid={`machine-${m.code}`}>
            <h3>
              {m.code}{" "}
              {/* Keyed by state, so a change of state shows as the pill fading in anew. */}
              <span key={m.state ?? "unknown"} className={`state state-${m.state ?? "unknown"}`}>
                <span aria-hidden="true">{m.state ? GLYPH[m.state] ?? "?" : "?"}</span>{" "}
                {m.state ? STATE[m.state] ?? m.state : "No answer"}
              </span>
            </h3>
            <p>
              {m.protocol}{" "}
              {m.source === "community" ? (
                <span className="badge badge-rush">community-documented protocol</span>
              ) : (
                <span className="badge">official docs</span>
              )}
            </p>
            {m.job || m.progress != null ? (
              <p>
                {m.job ? `Job ${m.job}` : ""}
                {m.progress != null ? `${m.job ? " · " : ""}Progress ${Math.round(m.progress * 100)} %` : ""}
              </p>
            ) : null}
            {m.message ? (
              <p className="muted">
                Machine says: <q>{m.message}</q>
              </p>
            ) : null}
            <p className="muted">
              <a href={m.docs}>Protocol docs</a>, read <span className="nowrap">{m.docs_read}</span>
            </p>
            {mayAsk ? (
              <details className="sim">
                <summary className="button-secondary">
                  Simulation settings<span className="visually-hidden"> for {m.code}</span>
                </summary>
                <SimulationForm code={m.code} idempotencyKey={crypto.randomUUID()} />
              </details>
            ) : null}
          </li>
        ))}
      </ul>
      {mayAsk && data.connected ? <AskButton idempotencyKey={crypto.randomUUID()} /> : null}
      {run ? <RunSection run={run} mayProceed={mayProceed} /> : <p role="status" className="lede">No dispatch yet.</p>}
    </>
  );
}

function RunSection({ run, mayProceed }: { run: Run; mayProceed: boolean }) {
  const rows: ProposalRow[] = run.proposals.map((p) => ({
    id: p.id,
    label: `${ACTION[p.action] ?? p.action} ${p.job} on ${p.machine}${p.executed ? " (carried out)" : p.approved ? " (approved)" : ""}`,
    detail: `${run.proposed_by === "code" ? "Code" : "Dispatcher"}: “${p.reason}” · check: ${p.precheck === "allowed" ? "passes" : `refused (${p.precheck}: ${p.precheck_detail})`}`,
    selectable: mayProceed && p.precheck === "allowed" && !p.approved,
  }));
  return (
    <section aria-labelledby="latest-run" data-testid="latest-run">
      <h2 id="latest-run">Latest dispatch</h2>
      <p role="note" className="lede" data-testid="proposed-by">
        {run.proposed_by === "code" ? `Proposed by code: ${run.note}` : "Proposed by the dispatcher (AI agent)."}
      </p>
      {rows.length === 0 ? (
        <p role="status" className="lede">
          No proposals: nothing is ready, or every machine is busy.
        </p>
      ) : mayProceed ? (
        <ProceedForm runId={run.id} proposals={rows} idempotencyKey={crypto.randomUUID()} />
      ) : (
        <ul>
          {rows.map((r) => (
            <li key={r.id}>
              {r.label} <span className="muted">{r.detail}</span>
            </li>
          ))}
        </ul>
      )}
      <h3>Tool calls and guard verdicts</h3>
      {run.calls.length === 0 ? (
        <p className="muted lede">None yet.</p>
      ) : (
        <div className="table-scroll" role="region" aria-label="Tool calls (scrolls sideways)" tabIndex={0}>
          <table>
            <caption className="visually-hidden">Every tool call, who made it, and what the guard decided</caption>
            <thead>
              <tr>
                <th scope="col">Made by</th>
                <th scope="col">Call</th>
                <th scope="col">Guard</th>
                <th scope="col">Machine answered</th>
              </tr>
            </thead>
            <tbody>
              {run.calls.map((c, i) => (
                <tr key={i} className="log-row" data-testid="call-row">
                  <td>{c.made_by === "code" ? `executed by code: ${c.why_code}` : "agent"}</td>
                  <td>
                    <code>
                      {c.tool}({Object.entries(c.args).filter(([k, v]) => k !== "tool" && v != null).map(([k, v]) => `${k}=${String(v)}`).join(", ")})
                    </code>
                  </td>
                  <td>{c.verdict === "allowed" ? "allowed" : `refused: ${c.verdict}`}{c.detail ? <span className="muted"> ({c.detail})</span> : null}</td>
                  <td>{c.result ? JSON.stringify(c.result) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
