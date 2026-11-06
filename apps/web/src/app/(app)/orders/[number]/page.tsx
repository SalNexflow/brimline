import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { signedInEngine, type HistoryEntry } from "@/lib/engine";

import { StatusPill } from "../../../ui";

export default function OrderPage({ params }: PageProps<"/orders/[number]">) {
  return (
    <main className="page">
      <p className="back">
        <Link href="/orders">← All orders</Link>
      </p>
      <Suspense fallback={<p>Loading order…</p>}>
        <Order params={params} />
      </Suspense>
    </main>
  );
}

async function Order({ params }: Pick<PageProps<"/orders/[number]">, "params">) {
  const { number } = await params;
  const { client } = await signedInEngine();
  const { data: order } = await client.GET("/orders/{order_number}", {
    params: { path: { order_number: number } },
  });
  // 404 covers both "does not exist" and "not yours": the engine does not tell them apart.
  if (!order) notFound();

  const history = order.can_view_history
    ? (
        await client.GET("/orders/{order_number}/history", {
          params: { path: { order_number: number } },
        })
      ).data
    : undefined;

  return (
    <>
      <h1 className="page-title">
        Order {order.order_number}
        {order.rush ? <span className="badge badge-rush">rush</span> : null}
      </h1>
      <dl className="facts facts-card">
        <dt>Customer</dt>
        <dd>{order.customer_name}</dd>
        <dt>Due</dt>
        <dd>{order.due_date}</dd>
        <dt>Status</dt>
        <dd>
          <StatusPill status={order.status} />
        </dd>
        <dt>Created by</dt>
        <dd>{order.created_by_name}</dd>
        {order.notes ? (
          <>
            <dt>Notes</dt>
            <dd>{order.notes}</dd>
          </>
        ) : null}
      </dl>

      <h2 id="jobs-heading">Jobs</h2>
      <div className="table-scroll" role="region" aria-labelledby="jobs-heading" tabIndex={0}>
        <table>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Part</th>
              <th scope="col" className="num">Quantity</th>
              <th scope="col">Material</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {order.lines.map((line) => (
              <tr key={line.line_no}>
                <td>{line.line_no}</td>
                <td>{line.part_name}</td>
                <td className="num">{line.quantity}</td>
                <td>{line.material_name}</td>
                <td>
                  <StatusPill status={line.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {history ? <History entries={history} /> : null}
    </>
  );
}

const utc = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

function History({ entries }: { entries: HistoryEntry[] }) {
  return (
    <section aria-labelledby="history-heading">
      <h2 id="history-heading">History</h2>
      {entries.length === 0 ? (
        <p className="muted lede">No recorded changes. (Seeded orders have no history.)</p>
      ) : (
        <div className="table-scroll" role="region" aria-labelledby="history-heading" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th scope="col">When (UTC)</th>
                <th scope="col">Who</th>
                <th scope="col">What</th>
                <th scope="col">Request key</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, i) => (
                <tr key={i}>
                  <td>{utc.format(new Date(entry.at))}</td>
                  <td>{entry.actor_name ?? "system"}</td>
                  <td>{entry.action}</td>
                  <td>
                    <code>{entry.idempotency_key ?? "—"}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
