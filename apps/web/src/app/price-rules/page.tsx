import { Suspense } from "react";

import { can, signedInEngine } from "@/lib/engine";

import { PriceRulesForm } from "./price-rules-form";

export default function PriceRulesPage() {
  return (
    <main className="page">
      <h1>Prices</h1>
      <p className="muted">
        Prices are versioned. A version never changes; to change prices, add a new version with the date it
        starts. Every quote records which version priced it.
      </p>
      <Suspense fallback={<p>Loading prices…</p>}>
        <Versions />
      </Suspense>
    </main>
  );
}

async function Versions() {
  const { client, me } = await signedInEngine();
  const { data: versions, response } = await client.GET("/price-rules");
  if (response.status === 403 || !versions) {
    return <p role="status">Your role does not see the shop&apos;s prices.</p>;
  }
  const today = new Date().toISOString().slice(0, 10);
  const current = versions.find((v) => v.effective_from <= today) ?? versions[versions.length - 1];
  const materials = can(me, "price_rules.write") ? ((await client.GET("/materials")).data ?? []) : [];

  return (
    <>
      <table>
        <caption className="visually-hidden">Price versions, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">Effective from</th>
            <th scope="col">Setup (c)</th>
            <th scope="col">Rush (%)</th>
            <th scope="col">FDM / resin / CNC (c/min)</th>
            <th scope="col">Added by</th>
            <th scope="col">Note</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id}>
              <td>
                {v.id}
                {v.id === current?.id ? <span className="badge">in effect</span> : null}
              </td>
              <td>{v.effective_from}</td>
              <td>{v.setup_cents}</td>
              <td>{v.rush_multiplier_percent}</td>
              <td>
                {v.machine_cents_per_minute.fdm} / {v.machine_cents_per_minute.resin} / {v.machine_cents_per_minute.cnc}
              </td>
              <td>{v.created_by_name ?? "seed"}</td>
              <td>{v.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {can(me, "price_rules.write") ? (
        <>
          <h2>Add a price version</h2>
          <PriceRulesForm current={current} materials={materials} idempotencyKey={crypto.randomUUID()} />
        </>
      ) : null}
    </>
  );
}
