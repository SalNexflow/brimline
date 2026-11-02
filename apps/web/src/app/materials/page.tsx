import type { Metadata } from "next";
import { Suspense } from "react";

import { can, signedInEngine, type StockOverview } from "@/lib/engine";
import { formatShopTime } from "@/lib/timeline";

import { Stats, StatusPill } from "../ui";
import { CancelButton, PurchaseOrderForm, ReceiveButton } from "./forms";

export const metadata: Metadata = { title: "Materials · Brimline" };

type PlanShortages = StockOverview["plans"][number];

export default function MaterialsPage({ searchParams }: PageProps<"/materials">) {
  return (
    <main className="page">
      <h1 className="page-title">Materials</h1>
      <Suspense fallback={<p>Loading materials…</p>}>
        <MaterialsContent searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

function grams(g: number): string {
  return `${g.toLocaleString("en-GB")} g`;
}

async function MaterialsContent({ searchParams }: { searchParams: PageProps<"/materials">["searchParams"] }) {
  const { client, me } = await signedInEngine();
  const { data, response } = await client.GET("/stock");
  if (response.status === 403 || !data) {
    return <p role="status">Your role does not see the shop&apos;s stock.</p>;
  }
  const params = await searchParams;
  const done =
    typeof params.recorded === "string"
      ? `${params.recorded} recorded.`
      : typeof params.received === "string"
        ? `${params.received} received; its grams are in stock.`
        : typeof params.cancelled === "string"
          ? `${params.cancelled} cancelled; planning no longer counts it.`
          : null;
  const tz = data.time_zone;
  const mayRecord = can(me, "purchase.record");
  // Pre-fill only from a plan made after the last purchase-order change: otherwise the order may
  // already be recorded (review of M9).
  const current = data.plans.filter((p) => !p.orders_changed);
  const firstShort = current.flatMap((p) => p.shortages).find((s) => s.suggestion);
  const firstSuggestion = firstShort?.suggestion;
  return (
    <>
      {done ? (
        <p role="status" className="toast">
          {done}
        </p>
      ) : null}
      <p className="lede">Stock, what runs short in each plan, and what to order. Brimline never orders anything.</p>
      <details className="how">
        <summary>How this works</summary>
        <p>
          Planning counts the stock on hand and every open purchase order at its expected time; no job starts before its
          material is there (checked by the independent checker). Shortages and suggestions are computed by code on every
          visit. A person orders from the supplier, then records it here.
        </p>
      </details>
      <Stats
        label="Stock and orders, counted by code"
        items={[
          ["Materials", data.stock.length],
          ["Short in a plan", new Set(current.flatMap((p) => p.shortages.map((s) => s.material))).size],
          ["Open purchase orders", data.purchase_orders.filter((po) => po.status === "open").length],
          ["Overdue", data.purchase_orders.filter((po) => po.overdue).length],
        ]}
      />
      {data.plans.length === 0 ? (
        <p role="status" className="lede">
          No plan yet: shortages appear once a plan is made.
        </p>
      ) : null}
      {data.plans.length > 1 ? (
        <p className="muted lede">
          The approved plan and the draft each have their own shortages. A suggestion that appears in both is the same
          need: order once.
        </p>
      ) : null}
      {data.plans.map((p) => (
        <PlanSection key={p.schedule_id} plan={p} timeZone={tz} />
      ))}

      <h2 id="stock-heading">Stock</h2>
      <div className="table-scroll" role="region" aria-labelledby="stock-heading" tabIndex={0}>
        <table>
          <caption className="visually-hidden">Stock on hand and on order</caption>
          <thead>
            <tr>
              <th scope="col">Material</th>
              <th scope="col" className="num">On hand</th>
              <th scope="col" className="num">On order</th>
              <th scope="col">Supplier (lead time)</th>
            </tr>
          </thead>
          <tbody>
            {data.stock.map((s) => (
              <tr key={s.material} data-testid={`stock-${s.material}`}>
                <td>
                  {s.material} <span className="muted">{s.name}</span>
                </td>
                <td className="num">{grams(s.on_hand_g)}</td>
                <td className="num">{s.on_order_g ? grams(s.on_order_g) : "—"}</td>
                <td>{s.supplier ? `${s.supplier} (${s.lead_time_days} days)` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 id="po-heading">Purchase orders</h2>
      {data.purchase_orders.length === 0 ? (
        <p role="status" className="lede">
          None recorded.
        </p>
      ) : (
        <div className="table-scroll" role="region" aria-labelledby="po-heading" tabIndex={0}>
          <table>
            <caption className="visually-hidden">Purchase orders, open first</caption>
            <thead>
              <tr>
                <th scope="col">Order</th>
                <th scope="col">Material</th>
                <th scope="col" className="num">Grams</th>
                <th scope="col">Supplier</th>
                <th scope="col">Expected</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.purchase_orders.map((po) => (
                <tr key={po.number} data-testid={`po-${po.number}`}>
                  <td>{po.number}</td>
                  <td>{po.material}</td>
                  <td className="num">{grams(po.grams)}</td>
                  <td>{po.supplier}</td>
                  <td>
                    {formatShopTime(po.expected_at, tz)}
                    {po.overdue ? <span className="badge badge-rush">overdue: not counted</span> : null}
                  </td>
                  <td>
                    <StatusPill status={po.status} />
                    {po.status === "received" && po.received_at ? (
                      <span className="muted"> {formatShopTime(po.received_at, tz)}</span>
                    ) : null}
                    {po.status === "open" && mayRecord ? (
                      <div className="task-actions">
                        <ReceiveButton number={po.number} idempotencyKey={crypto.randomUUID()} />
                        <CancelButton number={po.number} idempotencyKey={crypto.randomUUID()} />
                      </div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {mayRecord ? (
        <>
          <h2>Record a purchase order</h2>
          <p className="muted lede">
            After ordering from the supplier, record it so the next plan counts the delivery.
            {firstSuggestion && firstShort ? " Filled in from the first suggestion above." : null}
          </p>
          <PurchaseOrderForm
            materials={data.stock.map((s) => s.material)}
            timeZone={tz}
            idempotencyKey={crypto.randomUUID()}
            prefill={
              firstSuggestion && firstShort
                ? { material: firstShort.material, grams: firstSuggestion.grams, supplier: firstSuggestion.supplier }
                : {}
            }
          />
        </>
      ) : null}

      {data.movements.length > 0 ? (
        <>
          <h2>Latest stock changes</h2>
          <ul className="log-list">
            {data.movements.map((m, i) => (
              <li key={i}>
                {formatShopTime(m.at, tz)}: {m.grams > 0 ? "+" : ""}
                {grams(m.grams)} {m.material}, {m.what}
                {m.assumed ? <span className="muted"> (grams assumed, not weighed)</span> : null}
                {m.missing_g ? <span className="badge badge-rush">record was {grams(m.missing_g)} short: count the stock</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="muted lede">Purchasing settings from config/purchasing.toml, checked {data.checked}.</p>
    </>
  );
}

function PlanSection({ plan, timeZone }: { plan: PlanShortages; timeZone: string }) {
  const label = plan.status === "approved" ? "Approved plan" : "Draft plan";
  return (
    <section aria-labelledby={`plan-${plan.schedule_id}`} data-testid={`shortages-${plan.status}`}>
      <h2 id={`plan-${plan.schedule_id}`}>
        {label} <span className="muted">(made {formatShopTime(plan.made_at, timeZone)})</span>
      </h2>
      {plan.orders_changed ? (
        <p role="note" className="notice" data-testid={`orders-changed-${plan.status}`}>
          A purchase order was recorded, received or cancelled after this plan was made, so its shortages and
          suggestions may be out of date. Plan again on the board before ordering more.
        </p>
      ) : null}
      {!plan.material_known ? (
        <p role="status" className="lede">
          This plan was made before stock was part of planning; plan again to see shortages.
        </p>
      ) : plan.shortages.length === 0 ? (
        <p role="status" className="lede">
          No material runs short in this plan.
        </p>
      ) : (
        <ul className="flag-list shortage-list">
          {plan.shortages.map((s) => (
            <li key={s.material} className="card shortage" data-testid={`shortage-${s.material}`}>
              <p>
                <span className="state state-bad">
                  <span aria-hidden="true">!</span> short
                </span>{" "}
                <strong>{s.material}</strong> runs short {formatShopTime(s.short_at, timeZone)}, by {grams(s.short_by_g)}.
              </p>
              <ul>
                {s.affected.map((a) => (
                  <li key={a.job}>
                    {a.job} needs {grams(a.grams)} by {formatShopTime(a.needed_at, timeZone)} to be on time;{" "}
                    {a.planned_start
                      ? `planned to start ${formatShopTime(a.planned_start, timeZone)}${a.late_minutes ? `, ${Math.round(a.late_minutes / 60)} h late` : ""}`
                      : "not in this plan (no material within two weeks)"}
                    .
                  </li>
                ))}
              </ul>
              {s.suggestion ? (
                <p data-testid={`suggestion-${s.material}`}>
                  <strong>Suggestion:</strong> order {s.suggestion.packs} × {grams(s.suggestion.pack_grams)} from{" "}
                  {s.suggestion.supplier}{" "}
                  {s.suggestion.in_time ? `by ${s.suggestion.order_by}` : "today (the latest day to be in time has passed)"};{" "}
                  it would arrive {formatShopTime(s.suggestion.arrives_at, timeZone)} ({s.suggestion.lead_time_days} days).
                  {s.affected.some((a) => a.waits_after_order) ? " Some jobs above are needed before then and will still wait." : null}
                </p>
              ) : (
                <p>No supplier is set for {s.material} in config/purchasing.toml.</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
