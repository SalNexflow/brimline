"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { engineClient, errorMessage, type ConnectionTest } from "@/lib/engine";
import { readSessionToken } from "@/lib/session";

export type TestState = { error: string | null; result: ConnectionTest | null };

/** Test connection: one read-only status call through the machine's adapter. The engine records it,
    audits it and limits how often it may run; this only asks and reports. */
export async function testConnection(_previous: TestState, formData: FormData): Promise<TestState> {
  const token = await readSessionToken();
  if (!token) redirect("/login");
  const code = String(formData.get("code") ?? "");
  const { data, error, response } = await engineClient(token).POST("/machines/{code}/connection-tests", {
    params: { path: { code }, header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") } },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { error: errorMessage(response.status, error, "The connection could not be tested."), result: null };
  revalidatePath("/connectivity");
  return { error: null, result: data };
}
