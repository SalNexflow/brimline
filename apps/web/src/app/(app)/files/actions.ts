"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { engineHeaders } from "@/lib/demo";
import { engineClient, errorMessage } from "@/lib/engine";
import { parseUpload } from "@/lib/file-upload";
import { readSessionToken } from "@/lib/session";

export type FormState = { errors: string[] };

async function token(): Promise<string> {
  const value = await readSessionToken();
  if (!value) redirect("/login");
  return value;
}

/** Send the file as the raw request body; the engine reads, checks and stores it. */
export async function uploadModel(_previous: FormState, formData: FormData): Promise<FormState> {
  const parsed = parseUpload(formData);
  if (!parsed.ok) return { errors: parsed.errors };
  const { quote, order, line, unit, filename } = parsed.value;
  const file = formData.get("file") as File;
  const query = new URLSearchParams({ line: String(line), unit, filename });
  if (quote) query.set("quote", quote);
  if (order) query.set("order", order);
  const response = await fetch(`${process.env.ENGINE_URL}/files?${query}`, {
    method: "POST",
    headers: {
      ...(await engineHeaders()),
      Authorization: `Bearer ${await token()}`,
      "Content-Type": "application/octet-stream",
      "Idempotency-Key": String(formData.get("idempotency_key") ?? ""),
    },
    body: await file.arrayBuffer(),
    cache: "no-store",
  });
  if (response.status === 401) redirect("/login");
  const body = (await response.json().catch(() => ({}))) as { file_number?: string };
  if (!response.ok || !body.file_number) {
    return { errors: [errorMessage(response.status, body, "The file could not be checked.")] };
  }
  // A file can change a quote line, a job and so the board: none of them may be shown stale.
  revalidatePath("/", "layout");
  redirect(`/files/${body.file_number}`);
}

export async function acceptWarning(_previous: FormState, formData: FormData): Promise<FormState> {
  const number = String(formData.get("file_number") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  if (reason.length < 3) return { errors: ["Give a reason of at least 3 characters"] };
  const { data, error, response } = await engineClient(await token()).POST("/files/{file_number}/overrides", {
    params: {
      path: { file_number: number },
      header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") },
    },
    body: { check: String(formData.get("check") ?? ""), reason },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "The warning could not be accepted.")] };
  revalidatePath("/", "layout"); // accepting a unit warning can fill a part size
  redirect(`/files/${number}`);
}

export async function askAdvice(_previous: FormState, formData: FormData): Promise<FormState> {
  const number = String(formData.get("file_number") ?? "");
  const { data, error, response } = await engineClient(await token()).POST("/files/{file_number}/advice", {
    params: {
      path: { file_number: number },
      header: { "idempotency-key": String(formData.get("idempotency_key") ?? "") },
    },
  });
  if (response.status === 401) redirect("/login");
  if (!data) return { errors: [errorMessage(response.status, error, "No advice could be fetched.")] };
  redirect(`/files/${number}`);
}
