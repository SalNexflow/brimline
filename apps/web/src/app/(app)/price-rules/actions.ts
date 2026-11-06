"use server";

import { redirect } from "next/navigation";

import { engineClient, errorMessage } from "@/lib/engine";
import { parsePriceRules } from "@/lib/price-rules-form";
import { readSessionToken } from "@/lib/session";

export type PriceFormState = { errors: string[] };

export async function createPriceRules(_previous: PriceFormState, formData: FormData): Promise<PriceFormState> {
  const parsed = parsePriceRules(formData);
  if (!parsed.ok) return { errors: parsed.errors };
  const token = await readSessionToken();
  if (!token) redirect("/login");
  const { data, error, response } = await engineClient(token).POST("/price-rules", {
    body: parsed.value,
    params: { header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "The new prices could not be saved.")] };
  redirect("/price-rules");
}
