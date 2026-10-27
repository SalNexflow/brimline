"use server";

import { redirect } from "next/navigation";

import { engineClient } from "@/lib/engine";
import { readSessionToken } from "@/lib/session";
import { refusal } from "@/lib/task-labels";

export type ActionState = { error: string | null };

async function token(): Promise<string> {
  const value = await readSessionToken();
  if (!value) redirect("/login");
  return value;
}

/** Plan day: the engine records a run and answers at once; the board then shows its progress. */
export async function planDay(_previous: ActionState, formData: FormData): Promise<ActionState> {
  const { data, error, response } = await engineClient(await token()).POST("/planning-runs", {
    params: { header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { error: refusal(response.status, error, "Planning could not be started.") };
  redirect("/board");
}

/** Approve or discard a draft. The engine decides whether that is allowed (hard rule 7). */
export async function decide(_previous: ActionState, formData: FormData): Promise<ActionState> {
  const id = Number(formData.get("schedule_id"));
  const params = {
    path: { schedule_id: id },
    header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") },
  };
  const client = engineClient(await token());
  const { data, error, response } =
    formData.get("decision") === "discard"
      ? await client.POST("/schedules/{schedule_id}/discard", { params })
      : await client.POST("/schedules/{schedule_id}/approve", { params });
  if (response.status === 401) redirect("/login");
  if (!data) return { error: refusal(response.status, error, "The decision could not be saved.") };
  redirect("/board");
}
