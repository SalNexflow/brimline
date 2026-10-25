"use server";

import { redirect } from "next/navigation";

import { engineClient, errorMessage } from "@/lib/engine";
import { readSessionToken } from "@/lib/session";

export type SubmitState = { errors: string[] };

export async function submitQuoteRequest(_previous: SubmitState, formData: FormData): Promise<SubmitState> {
  const customer_code = String(formData.get("customer_code") ?? "");
  const message = String(formData.get("message") ?? "").trim();
  const errors = [
    ...(customer_code ? [] : ["Choose a customer"]),
    ...(message ? [] : ["Paste or type the customer's message"]),
    ...(message.length > 10_000 ? ["The message can be at most 10,000 characters"] : []),
  ];
  if (errors.length > 0) return { errors };

  const token = await readSessionToken();
  if (!token) redirect("/login");
  // One key per rendered form: a double click or a retry never creates (or pays for) a second draft.
  const key = String(formData.get("idempotency_key") ?? "");
  const { data, error, response } = await engineClient(token).POST("/quote-requests", {
    body: { customer_code, message },
    params: { header: { "idempotency-key": key } },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "The request could not be saved.")] };
  redirect(`/quotes/${data.quote_number}`);
}
