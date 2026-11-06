import type { Metadata } from "next";
import { Suspense } from "react";

import { can, signedInEngine } from "@/lib/engine";

import { AutoRefresh } from "../../auto-refresh";
import { SimulationForm } from "../dispatch/forms";
import { Stats } from "../../ui";
import { TestConnectionForm } from "./forms";
import { MachineCard } from "./view";

export const metadata: Metadata = { title: "Connectivity · Brimline" };

export default function ConnectivityPage({ searchParams }: PageProps<"/connectivity">) {
  return (
    <main className="page">
      <h1 className="page-title">Connectivity</h1>
      <Suspense fallback={<p>Reading the recorded polls…</p>}>
        <ConnectivityContent searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function ConnectivityContent({ searchParams }: { searchParams: PageProps<"/connectivity">["searchParams"] }) {
  const { client, me } = await signedInEngine();
  const { data, response } = await client.GET("/connectivity");
  if (response.status === 403 || !data) {
    return <p role="status">Your role does not see the machines&apos; connections.</p>;
  }
  const params = await searchParams;
  const mayTest = can(me, "dispatch.read");
  const maySimulate = can(me, "dispatch.ask");
  const t = data.thresholds;
  const count = (state: string) => data.machines.filter((m) => m.state === state).length;
  return (
    <>
      {/* The page reads recorded polls, never the machines, so refreshing it costs them nothing. */}
      <AutoRefresh active everyMs={5000} />
      <p role="note" className="notice" data-testid="simulated-notice">
        {data.simulated_notice}
      </p>
      {params.simulated ? (
        <p role="status" className="toast">
          Simulation of {String(params.simulated)} changed. The next poll, or Test connection, shows the effect.
        </p>
      ) : null}
      <p className="lede">Whether each machine answers, and how fast. Code judges it from the engine&apos;s polls.</p>
      <details className="how">
        <summary>How this works</summary>
        <p>
          Every {t.poll_seconds} s the engine asks each machine for its status, one read-only call, and records the
          answer and how long it took. From the recorded polls, code decides: <strong>unreachable</strong> when the
          last {t.unreachable_after} polls got no usable answer; <strong>slow</strong> when the median time of the last{" "}
          {t.slow_window} answers is {t.slow_ms} ms or more; <strong>no data yet</strong> when nothing was polled in the
          last {t.stale_seconds} s (the hosted engine sleeps when nobody uses it); otherwise <strong>connected</strong>.
          Uptime is the share of polls answered in the last {t.uptime_minutes} minutes.
        </p>
        <p>
          A <strong>fault</strong> is kept apart from the connection: a machine that answers every poll but reports a
          failure, or refused the last start sent to it, is connected, with a fault. Text from a machine is shown in
          quotes as it came and never acted on. Test connection makes one status call now; each person may test a
          machine once every {t.test_every_seconds} s. Thresholds are set in config/connectivity.toml (checked{" "}
          {t.checked}).
        </p>
      </details>
      {!data.connected ? <p role="status">No machines are connected (SIM_MACHINES is off).</p> : null}
      <Stats
        label="Machines by connection, from recorded polls"
        items={[
          ["Connected", count("connected")],
          ["Slow", count("slow")],
          ["Unreachable", count("unreachable")],
          ["No data yet", count("no_data")],
        ]}
      />
      <h2>Machines</h2>
      <ul className="machine-grid">
        {data.machines.map((m) => (
          <MachineCard
            key={m.code}
            m={m}
            now={data.now}
            timeZone={data.time_zone}
            uptimeMinutes={t.uptime_minutes}
            actions={
              <>
                {mayTest ? <TestConnectionForm code={m.code} idempotencyKey={crypto.randomUUID()} /> : null}
                {maySimulate ? (
                  <details className="sim">
                    <summary className="button-secondary">
                      Simulation settings<span className="visually-hidden"> for {m.code}</span>
                    </summary>
                    <SimulationForm code={m.code} idempotencyKey={crypto.randomUUID()} returnTo="/connectivity" />
                  </details>
                ) : null}
              </>
            }
          />
        ))}
      </ul>
    </>
  );
}
