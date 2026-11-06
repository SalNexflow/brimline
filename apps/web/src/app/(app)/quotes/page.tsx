import Link from "next/link";
import { Suspense } from "react";

import { can, signedInEngine } from "@/lib/engine";
import { formatMoney } from "@/lib/money";

export default function QuotesPage() {
  return (
    <main className="page">
      <Suspense fallback={<p>Loading quotes…</p>}>
        <Quotes />
      </Suspense>
    </main>
  );
}

async function Quotes() {
  const { client, me } = await signedInEngine();
  const { data: quotes, response } = await client.GET("/quotes");

  return (
    <>
      <div className="page-title">
        <h1>Quotes</h1>
        {can(me, "quote.submit") ? (
          <Link href="/quotes/new" className="button">
            New quote request
          </Link>
        ) : null}
      </div>
      {response.status === 403 ? (
        <p role="status">Your role does not work with quotes.</p>
      ) : !quotes || quotes.length === 0 ? (
        <p>No quote requests yet.</p>
      ) : (
        <div className="table-scroll" role="region" aria-label="Quote requests (scrolls sideways)" tabIndex={0}>
          <table>
            <caption className="visually-hidden">Quotes you can see</caption>
            <thead>
              <tr>
                <th scope="col">Quote</th>
                <th scope="col">Customer</th>
                <th scope="col">Status</th>
                <th scope="col">Lines</th>
                <th scope="col">Still missing</th>
                <th scope="col">Total</th>
              </tr>
            </thead>
            <tbody>
              {quotes.map((quote) => (
                <tr key={quote.quote_number}>
                  <td>
                    <Link href={`/quotes/${quote.quote_number}`}>{quote.quote_number}</Link>
                  </td>
                  <td>{quote.customer_name}</td>
                  <td>{quote.status}</td>
                  <td>{quote.line_count}</td>
                  <td>{quote.missing_count}</td>
                  <td>{quote.total_cents == null ? "—" : formatMoney(quote.total_cents, quote.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
