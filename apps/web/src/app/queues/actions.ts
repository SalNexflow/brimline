"use server";

import { redirect } from "next/navigation";

import { engineClient } from "@/lib/engine";
import { readSessionToken } from "@/lib/session";
import { refusal } from "@/lib/task-labels";

export type ActionState = { error: string | null };

/** Start, finish or fail a task. The engine enforces the order and one task per machine. */
export async function actOnTask(_previous: ActionState, formData: FormData): Promise<ActionState> {
  const token = await readSessionToken();
  if (!token) redirect("/login");
  const raw = String(formData.get("action") ?? "");
  const action = raw === "done" || raw === "fail" ? raw : "start";
  const { data, error, response } = await engineClient(token).POST("/tasks/{task_id}/{action}", {
    params: {
      path: { task_id: Number(formData.get("task_id")), action },
      header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") },
    },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { error: refusal(response.status, error, "The task could not be updated.") };
  redirect("/queues");
}
