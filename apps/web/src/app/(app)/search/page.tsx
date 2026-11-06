import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { signedInEngine } from "@/lib/engine";
import { decodeFilter, type Filter } from "@/lib/search-filter";

import { ChipsEditor, QuestionForm } from "./forms";

export const metadata: Metadata = { title: "Search · Brimline" };

export default function SearchPage({ searchParams }: PageProps<"/search">) {
  return (
    <main className="page">
      <h1>Search</h1>
      <QuestionForm />
      <Suspense fallback={<p>Searching…</p>}>
        <Results searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Results({ searchParams }: Pick<PageProps<"/search">, "searchParams">) {
  const query = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const filter = decodeFilter(one(query.f));
  const { client } = await signedInEngine();
  if (!filter) return <ChipsEditor key="empty" filter={{ conditions: [], sort: "due_date" }} />;
  // Chips and links run the filter as it is: no model call. The engine adds permissions.
  const { data, error, response } = await client.POST("/search/run", { body: filter });
  if (!data) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    return (
      <>
        <p role="alert" className="error-box">
          {typeof detail === "string" ? detail : `The filter could not run (${response.status}).`}
        </p>
        <ChipsEditor key={one(query.f)} filter={filter} />
      </>
    );
  }
  const ran = (data.filter ?? filter) as Filter;
  // One customer in the filter (always so for a customer): the column would repeat it.
  const customer = ran.conditions.find((c) => c.field === "customer");
  const customerView = Array.isArray(customer?.value) && customer.value.length === 1;
  return (
    <>
      {one(query.narrowed) ? (
        <p role="status" className="notice">
          Showing your own orders only: you can only search your own orders.
        </p>
      ) : null}
      {one(query.flagged) ? (
        <p className="muted">The question seemed to give the system instructions; they were ignored.</p>
      ) : null}
      <p data-testid="search-description">{data.description}</p>
      <ChipsEditor key={one(query.f)} filter={ran} />
      <h2>
        Results <span className="muted">({data.total.toLocaleString("en")} jobs{data.limited ? `, first ${data.rows.length} shown` : ""})</span>
      </h2>
      {data.rows.length === 0 ? (
        <p>No jobs match.</p>
      ) : (
        <div className="table-scroll" role="region" aria-label="Search results" tabIndex={0}>
          <table>
            <thead>
              <tr>
                <th scope="col">Order</th>
                <th scope="col">Part</th>
                <th scope="col">Qty</th>
                <th scope="col">Material</th>
                {customerView ? null : <th scope="col">Customer</th>}
                <th scope="col">Due</th>
                <th scope="col">Order status</th>
                <th scope="col">Job status</th>
                <th scope="col">Printed</th>
                <th scope="col">Can plan</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={`${r.order_number}-${r.line_no}`}>
                  <td>
                    <Link href={`/orders/${r.order_number}`}>{r.order_number}</Link>-{r.line_no}
                    {r.rush ? <span className="badge badge-rush"> rush</span> : null}
                  </td>
                  <td>{r.part_name}</td>
                  <td>{r.quantity}</td>
                  <td>{r.material_code}</td>
                  {customerView ? null : <td>{r.customer_name}</td>}
                  <td>{r.due_date}</td>
                  <td>{r.order_status}</td>
                  <td>{r.job_status}</td>
                  <td>{r.printed ? "yes" : "no"}</td>
                  <td>{r.can_plan ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
