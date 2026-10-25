"use server";

import { redirect } from "next/navigation";

import { engineClient, errorMessage } from "@/lib/engine";
import { parseQuoteEdit } from "@/lib/quote-form";
import { readSessionToken } from "@/lib/session";

export type FormState = { errors: string[] };

async function token(): Promise<string> {
  const value = await readSessionToken();
  if (!value) redirect("/login");
  return value;
}

export async function saveQuote(_previous: FormState, formData: FormData): Promise<FormState> {
  const number = String(formData.get("quote_number") ?? "");
  const parsed = parseQuoteEdit(formData);
  if (!parsed.ok) return { errors: parsed.errors };
  const { data, error, response } = await engineClient(await token()).PUT("/quotes/{quote_number}", {
    params: {
      path: { quote_number: number },
      header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") },
    },
    body: parsed.value,
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "The quote could not be saved.")] };
  redirect(`/quotes/${number}`);
}

export async function decideQuote(_previous: FormState, formData: FormData): Promise<FormState> {
  const number = String(formData.get("quote_number") ?? "");
  const decision = formData.get("decision") === "reject" ? "reject" : "approve";
  const { data, error, response } = await engineClient(await token()).POST(
    "/quotes/{quote_number}/decision",
    {
      params: {
        path: { quote_number: number },
        header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") },
      },
      body: { decision },
    },
  );
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "The decision could not be saved.")] };
  redirect(`/quotes/${number}`);
}
