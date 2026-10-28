"use server";

import { redirect } from "next/navigation";

import { engineClient, errorMessage } from "@/lib/engine";
import { encodeFilter, type Filter } from "@/lib/search-filter";
import { readSessionToken } from "@/lib/session";

export type AskState = {
  error: string | null;
  reason: string | null; // unclear or needs confirmation, written by the engine's code
  options: { label: string; href: string }[]; // one per reading of a date
  injection: boolean;
};

async function token(): Promise<string> {
  const value = await readSessionToken();
  if (!value) redirect("/login");
  return value;
}

/** Read a question (one model call), then show its filter: the chips run it from then on. */
export async function askSearch(_previous: AskState, formData: FormData): Promise<AskState> {
  const question = String(formData.get("question") ?? "").trim();
  if (!question) return { error: "Type a question first.", reason: null, options: [], injection: false };
  const { data, error, response } = await engineClient(await token()).POST("/search", { body: { question } });
  if (response.status === 401) redirect("/login");
  if (!data) {
    return { error: errorMessage(response.status, error, "The search failed."), reason: null, options: [], injection: false };
  }
  if (data.kind === "filter" && data.filter) {
    const params = new URLSearchParams({ f: encodeFilter(data.filter as Filter) });
    if (data.notices.length > 0) params.set("narrowed", "1");
    if (data.injection_suspected) params.set("flagged", "1");
    redirect(`/search?${params}`);
  }
  return {
    error: null,
    reason: data.reason,
    options: data.options.map((option, i) => ({
      label: `Use ${data.readings[i] ?? "this reading"}`,
      href: `/search?f=${encodeFilter(option as Filter)}`,
    })),
    injection: data.injection_suspected,
  };
}
