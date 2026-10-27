"use server";

import { redirect } from "next/navigation";

import { eventsFromForm } from "@/lib/disruption-form";
import { engineClient } from "@/lib/engine";
import { readSessionToken } from "@/lib/session";
import { refusal } from "@/lib/task-labels";

export type FormState = { errors: string[] };

async function client() {
  const token = await readSessionToken();
  if (!token) redirect("/login");
  return engineClient(token);
}

function header(formData: FormData) {
  return { "idempotency-key": String(formData.get("idempotency_key") ?? "") };
}

/** The model reads the message into events for the planner to check. Nothing else changes. */
export async function readMessage(_previous: FormState, formData: FormData): Promise<FormState> {
  const message = String(formData.get("message") ?? "").trim();
  if (!message) return { errors: ["Type what happened."] };
  const { data, error, response } = await (await client()).POST("/disruptions", {
    params: { header: header(formData) },
    body: { message },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [refusal(response.status, error, "The message could not be read.")] };
  // A query string, not only a #hash: a hash-only change is a scroll, and the board would not reload.
  redirect(`/board?disruption=${data.id}#disruption-${data.id}`);
}

/** Confirm the events (as read, or corrected), or enter them by hand without a message. */
export async function confirmEvents(_previous: FormState, formData: FormData): Promise<FormState> {
  const c = await client();
  // The shop's time zone comes from the engine, never from the form (review of M6): a stale or
  // edited value would shift every time sent.
  const { data: catalog } = await c.GET("/disruptions/catalog");
  if (!catalog) return { errors: ["The shop's settings could not be read; try again."] };
  const parsed = eventsFromForm(formData, catalog.time_zone);
  if (!parsed.ok) return { errors: parsed.errors };
  const id = Number(formData.get("disruption_id") ?? 0);
  const body = { events: parsed.events, acknowledged_warnings: formData.get("acknowledged") === "on" };
  const { data, error, response } = id
    ? await c.POST("/disruptions/{disruption_id}/confirm", {
        params: { path: { disruption_id: id }, header: header(formData) },
        body,
      })
    : await c.POST("/disruptions/by-hand", { params: { header: header(formData) }, body });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [refusal(response.status, error, "The events could not be saved.")] };
  // A query string, not only a #hash: a hash-only change is a scroll, and the board would not reload.
  redirect(`/board?disruption=${data.id}#disruption-${data.id}`);
}

export async function dismissDisruption(_previous: FormState, formData: FormData): Promise<FormState> {
  const id = Number(formData.get("disruption_id") ?? 0);
  const { data, error, response } = await (await client()).POST("/disruptions/{disruption_id}/dismiss", {
    params: { path: { disruption_id: id }, header: header(formData) },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [refusal(response.status, error, "It could not be dismissed.")] };
  redirect("/board");
}
