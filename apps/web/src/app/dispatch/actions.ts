"use server";

import { redirect } from "next/navigation";

import { engineClient, errorMessage } from "@/lib/engine";
import { readSessionToken } from "@/lib/session";

export type DispatchState = { error: string | null };

async function token(): Promise<string> {
  const t = await readSessionToken();
  if (!t) redirect("/login");
  return t;
}

/** Ask the dispatcher for proposals. Nothing reaches a machine yet. */
export async function askDispatcher(_previous: DispatchState, formData: FormData): Promise<DispatchState> {
  const { data, error, response } = await engineClient(await token()).POST("/dispatch/runs", {
    params: { header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { error: errorMessage(response.status, error, "The dispatcher could not be asked.") };
  redirect("/dispatch?asked=1");
}

/** Proceed: approve the ticked proposals; the engine then carries them out through the guard. */
export async function proceedWith(_previous: DispatchState, formData: FormData): Promise<DispatchState> {
  const ids = formData.getAll("proposal_id").map((v) => Number(v)).filter((n) => Number.isInteger(n) && n > 0);
  if (ids.length === 0) return { error: "Tick at least one proposal to approve." };
  const runId = Number(formData.get("run_id"));
  const { data, error, response } = await engineClient(await token()).POST("/dispatch/runs/{run_id}/proceed", {
    params: { path: { run_id: runId }, header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
    body: { proposal_ids: ids },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { error: errorMessage(response.status, error, "Proceed could not be recorded.") };
  redirect("/dispatch?proceeded=1");
}

/** Simulation only: make a machine fail, slow down, stop answering, look busy, or say something. */
export async function setSimulation(_previous: DispatchState, formData: FormData): Promise<DispatchState> {
  const code = String(formData.get("code") ?? "");
  const mode = String(formData.get("mode") ?? "success") as "success" | "failure" | "slow" | "unresponsive";
  const { data, error, response } = await engineClient(await token()).POST("/machines/{code}/simulation", {
    params: { path: { code }, header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
    body: { mode, busy: formData.get("busy") === "on", message: String(formData.get("message") ?? "").slice(0, 300) },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { error: errorMessage(response.status, error, "The simulation could not be changed.") };
  redirect("/dispatch?simulated=" + encodeURIComponent(code));
}
