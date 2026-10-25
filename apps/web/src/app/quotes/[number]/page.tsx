import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { signedInEngine, type QuoteDetail } from "@/lib/engine";
import { formatMoney } from "@/lib/money";

import { DecisionForm, ReviewForm } from "./review-form";

export default function QuotePage({ params }: PageProps<"/quotes/[number]">) {
  return (
    <main className="page">
      <p>
        <Link href="/quotes">← All quotes</Link>
      </p>
      <Suspense fallback={<p>Loading quote…</p>}>
        <Quote params={params} />
      </Suspense>
    </main>
  );
}

async function Quote({ params }: Pick<PageProps<"/quotes/[number]">, "params">) {
  const { number } = await params;
  const { client } = await signedInEngine();
  const { data: quote } = await client.GET("/quotes/{quote_number}", {
    params: { path: { quote_number: number } },
  });
  if (!quote) notFound();
  const materials = quote.can_edit ? ((await client.GET("/materials")).data ?? []) : [];

  return (
    <>
      <h1>
        Quote {quote.quote_number} <span className="badge">{quote.status}</span>
      </h1>
      <dl className="facts">
        <dt>Customer</dt>
        <dd>{quote.customer_name}</dd>
        <dt>Received</dt>
        <dd>{new Date(quote.received_at).toISOString().slice(0, 16).replace("T", " ")} UTC</dd>
        <dt>Sent by</dt>
        <dd>{quote.submitted_by_name}</dd>
        {quote.order_number ? (
          <>
            <dt>Order</dt>
            <dd>
              <Link href={`/orders/${quote.order_number}`}>{quote.order_number}</Link>
            </dd>
          </>
        ) : null}
      </dl>

      <h2>Customer message</h2>
      <blockquote className="message">{quote.message}</blockquote>

      {quote.ai ? (
        <p className="muted">
          Drafted by {quote.ai.model ?? "nobody (AI off)"} · {quote.ai.outcome} · {quote.ai.prompt_version} · $
          {(quote.ai.cost_micro_usd / 1_000_000).toFixed(4)} · {quote.ai.latency_ms} ms
        </p>
      ) : null}

      {quote.requests_for_staff && quote.requests_for_staff.length > 0 ? (
        <div className="notice" role="note" aria-label="Requests for staff">
          <p>
            <strong>The customer asked for something only staff can decide.</strong> Nothing below was changed because
            of it:
          </p>
          <ul>
            {quote.requests_for_staff.map((request) => (
              <li key={request}>{request}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <Gaps quote={quote} />
      <Price quote={quote} />

      {quote.can_edit ? (
        <>
          <h2>Review</h2>
          <ReviewForm quote={quote} materials={materials} editKey={crypto.randomUUID()} />
        </>
      ) : (
        <ReadOnlyLines quote={quote} />
      )}

      {quote.can_decide ? (
        <>
          <h2>Decision</h2>
          <DecisionForm quoteNumber={quote.quote_number} decideKey={crypto.randomUUID()} />
        </>
      ) : null}
    </>
  );
}

function Gaps({ quote }: { quote: QuoteDetail }) {
  if (quote.status !== "draft" || quote.missing.length === 0) return null;
  return (
    <section aria-labelledby="missing-heading" className="notice">
      <h2 id="missing-heading">Still missing</h2>
      <ul>
        {quote.missing.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {quote.questions_for_customer.length > 0 ? (
        <>
          <p>Questions you could send the customer:</p>
          <ul>
            {quote.questions_for_customer.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

function Price({ quote }: { quote: QuoteDetail }) {
  if (quote.price) {
    const money = (cents: number) => formatMoney(cents, quote.currency);
    return (
      <section aria-labelledby="price-heading">
        <h2 id="price-heading">Price</h2>
        <table>
          <thead>
            <tr>
              <th scope="col">Line</th>
              <th scope="col">Material</th>
              <th scope="col">Machine time</th>
              <th scope="col">Post-processing</th>
              <th scope="col">Setup</th>
              <th scope="col">Line total</th>
            </tr>
          </thead>
          <tbody>
            {quote.price.lines.map((line, i) => (
              <tr key={i}>
                <td>{i + 1}</td>
                <td>{money(line.material_cents)}</td>
                <td>{money(line.machine_cents)}</td>
                <td>{money(line.post_process_cents)}</td>
                <td>{money(line.setup_cents)}</td>
                <td>{money(line.total_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl className="facts">
          <dt>Subtotal</dt>
          <dd>{money(quote.price.subtotal_cents)}</dd>
          <dt>Rush surcharge</dt>
          <dd>{money(quote.price.rush_surcharge_cents)}</dd>
          <dt>Total</dt>
          <dd data-testid="quote-total">
            <strong>{money(quote.price.total_cents)}</strong>
          </dd>
        </dl>
        <p className="muted">Calculated by the shop&apos;s price rules (version {quote.price.rule_set_id}), not by AI.</p>
      </section>
    );
  }
  if (quote.price_pending.length > 0) {
    return (
      <p className="muted" data-testid="price-pending">
        Price pending: {quote.price_pending.join("; ")}.
      </p>
    );
  }
  return quote.status === "draft" ? <p className="muted">The price is shown once the shop approves the quote.</p> : null;
}

function ReadOnlyLines({ quote }: { quote: QuoteDetail }) {
  return (
    <>
      <h2>Lines</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Part</th>
            <th scope="col">Quantity</th>
            <th scope="col">Material</th>
            <th scope="col">Post-processing</th>
          </tr>
        </thead>
        <tbody>
          {quote.lines.map((line) => (
            <tr key={line.line_no}>
              <td>{line.line_no}</td>
              <td>{line.part_name}</td>
              <td>{line.quantity ?? "to be confirmed"}</td>
              <td>{line.material_name ?? line.material_as_written ?? "to be confirmed"}</td>
              <td>{line.post_processing.join(", ") || "none"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>Due: {quote.due_date ?? "to be confirmed"}</p>
    </>
  );
}
