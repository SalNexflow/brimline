import Link from "next/link";
import { Suspense } from "react";

import { can, signedInEngine } from "@/lib/engine";

import { Stats, StatusPill } from "../ui";

export default function OrdersPage() {
  return (
    <main className="page">
      <Suspense fallback={<p>Loading orders…</p>}>
        <Orders />
      </Suspense>
    </main>
  );
}

async function Orders() {
  const { client, me } = await signedInEngine();
  const { data: orders } = await client.GET("/orders");

  return (
    <>
      <div className="page-title">
        <h1>Orders</h1>
        {can(me, "order.create") ? (
          <Link href="/orders/new" className="button">
            New order
          </Link>
        ) : null}
      </div>
      {!orders || orders.length === 0 ? (
        <p className="lede">No orders yet.</p>
      ) : (
        <>
          <Stats
            label="Orders you can see, counted by code"
            items={[
              ["Orders", orders.length],
              ["Open or in production", orders.filter((o) => o.status === "open" || o.status === "in_production").length],
              ["Rush", orders.filter((o) => o.rush).length],
              ["Done", orders.filter((o) => o.status === "done").length],
            ]}
          />
          <div className="table-scroll" role="region" aria-label="Orders (scrolls sideways)" tabIndex={0}>
            <table>
              <caption className="visually-hidden">Orders you can see</caption>
              <thead>
                <tr>
                  <th scope="col">Order</th>
                  <th scope="col">Customer</th>
                  <th scope="col">Due</th>
                  <th scope="col" className="num">Lines</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr key={order.order_number}>
                    <td>
                      <Link href={`/orders/${order.order_number}`}>{order.order_number}</Link>
                      {order.rush ? <span className="badge badge-rush">rush</span> : null}
                    </td>
                    <td>{order.customer_name}</td>
                    <td>{order.due_date}</td>
                    <td className="num">{order.line_count}</td>
                    <td>
                      <StatusPill status={order.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
