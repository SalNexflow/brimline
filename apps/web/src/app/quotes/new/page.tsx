import Link from "next/link";
import { Suspense } from "react";

import { can, signedInEngine } from "@/lib/engine";

import { RequestForm } from "./request-form";

export default function NewQuoteRequestPage() {
  return (
    <main className="page">
      <p>
        <Link href="/quotes">← All quotes</Link>
      </p>
      <h1>New quote request</h1>
      <Suspense fallback={<p>Loading form…</p>}>
        <NewRequest />
      </Suspense>
    </main>
  );
}

async function NewRequest() {
  const { client, me } = await signedInEngine();
  if (!can(me, "quote.submit")) {
    return <p role="alert">Your role cannot send quote requests.</p>;
  }
  const customers = can(me, "customer.list") ? ((await client.GET("/customers")).data ?? []) : null;
  const ownCustomer =
    me.role === "customer" && me.customer_code && me.customer_name
      ? { code: me.customer_code, name: me.customer_name }
      : null;
  return (
    <RequestForm idempotencyKey={crypto.randomUUID()} customers={customers} ownCustomer={ownCustomer} />
  );
}
