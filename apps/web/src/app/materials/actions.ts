"use server";

import { redirect } from "next/navigation";

import { engineClient, errorMessage } from "@/lib/engine";
import { parsePurchaseOrder } from "@/lib/purchase-order-form";
import { readSessionToken } from "@/lib/session";

export type PoFormState = { errors: string[] };

/** Record an order a person has already placed with a supplier. Brimline never orders. */
export async function recordPurchaseOrder(_previous: PoFormState, formData: FormData): Promise<PoFormState> {
  const parsed = parsePurchaseOrder(formData, String(formData.get("time_zone") ?? "UTC"));
  if (!parsed.ok) return { errors: parsed.errors };
  const token = await readSessionToken();
  if (!token) redirect("/login");
  const { data, error, response } = await engineClient(token).POST("/purchase-orders", {
    body: parsed.value,
    params: { header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "The purchase order could not be recorded.")] };
  redirect(`/materials?recorded=${encodeURIComponent(String(data.number))}`);
}

/** The delivery arrived: its grams go into stock. */
export async function receivePurchaseOrder(_previous: PoFormState, formData: FormData): Promise<PoFormState> {
  const token = await readSessionToken();
  if (!token) redirect("/login");
  const number = String(formData.get("number") ?? "");
  const { data, error, response } = await engineClient(token).POST("/purchase-orders/{number}/receive", {
    params: { path: { number }, header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "The delivery could not be recorded.")] };
  redirect(`/materials?received=${encodeURIComponent(number)}`);
}
