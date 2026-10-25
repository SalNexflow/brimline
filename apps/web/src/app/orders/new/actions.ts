"use server";

import { redirect } from "next/navigation";

import { engineClient } from "@/lib/engine";
import { parseOrderForm } from "@/lib/order-form";
import { readSessionToken } from "@/lib/session";

export type CreateOrderState = { errors: string[] };

const MESSAGES: Record<number, string> = {
  403: "You are not allowed to create this order.",
  409: "This form was already sent with different details. Reload the page to start a new order.",
};

export async function createOrder(
  _previous: CreateOrderState,
  formData: FormData,
): Promise<CreateOrderState> {
  const parsed = parseOrderForm(formData);
  if (!parsed.ok) return { errors: parsed.errors };

  const token = await readSessionToken();
  if (!token) redirect("/login");

  // The key was generated when the form was rendered, so a double click or a retry after a
  // network error replays the first result instead of creating a second order.
  const key = String(formData.get("idempotency_key") ?? "");
  const { data, error, response } = await engineClient(token).POST("/orders", {
    body: parsed.value,
    params: { header: { "idempotency-key": key } },
  });

  if (response.status === 401) redirect("/login");
  if (!data) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    const message =
      MESSAGES[response.status] ??
      (typeof detail === "string" ? detail : "The order could not be saved. Check the form.");
    return { errors: [message] };
  }
  redirect(`/orders/${data.order_number}`);
}
