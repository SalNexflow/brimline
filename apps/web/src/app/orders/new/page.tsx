import Link from "next/link";
import { Suspense } from "react";

import { can, signedInEngine } from "@/lib/engine";

import { OrderForm } from "./order-form";

export default function NewOrderPage() {
  return (
    <main className="page">
      <p>
        <Link href="/orders">← All orders</Link>
      </p>
      <h1>New order</h1>
      <Suspense fallback={<p>Loading form…</p>}>
        <NewOrder />
      </Suspense>
    </main>
  );
}

async function NewOrder() {
  const { client, me } = await signedInEngine();
  if (!can(me, "order.create")) {
    return <p role="alert">Your role cannot create orders.</p>;
  }
  const [materials, customers] = await Promise.all([
    client.GET("/materials").then((r) => r.data ?? []),
    can(me, "customer.list") ? client.GET("/customers").then((r) => r.data ?? []) : null,
  ]);
  const ownCustomer =
    me.role === "customer" && me.customer_code && me.customer_name
      ? { code: me.customer_code, name: me.customer_name }
      : null;

  // A new key per rendered form: one form, one order, however many times it is submitted.
  return (
    <OrderForm
      idempotencyKey={crypto.randomUUID()}
      materials={materials}
      customers={customers}
      ownCustomer={ownCustomer}
    />
  );
}
