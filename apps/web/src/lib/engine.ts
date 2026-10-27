import "server-only";

import createClient from "openapi-fetch";
import { redirect } from "next/navigation";

import type { components, paths } from "./engine-api";
import { readSessionToken } from "./session";

export type Me = components["schemas"]["Me"];
export type OrderSummary = components["schemas"]["OrderSummary"];
export type OrderDetail = components["schemas"]["OrderDetail"];
export type HistoryEntry = components["schemas"]["HistoryEntry"];
export type Material = components["schemas"]["MaterialOut"];
export type Customer = components["schemas"]["CustomerOut"];
export type DemoUser = components["schemas"]["DemoUser"];
export type QuoteSummary = components["schemas"]["QuoteSummary"];
export type QuoteDetail = components["schemas"]["QuoteDetail"];
export type QuoteLine = components["schemas"]["QuoteLineOut"];
export type PriceRules = components["schemas"]["PriceRulesOut"];
export type Board = components["schemas"]["BoardOut"];
export type Schedule = components["schemas"]["ScheduleOut"];
export type BoardTask = components["schemas"]["BoardTask"];
export type BoardJob = components["schemas"]["BoardJob"];
export type PlanningRun = components["schemas"]["PlanningRun"];
export type Queues = components["schemas"]["QueuesOut"];
export type QueueTask = components["schemas"]["QueueTask"];

function baseUrl(): string {
  const url = process.env.ENGINE_URL;
  if (!url) throw new Error("ENGINE_URL is not set (see .env.example)");
  return url;
}

/** A typed client for the engine, optionally signed in with a session token. */
export function engineClient(token?: string) {
  return createClient<paths>({
    baseUrl: baseUrl(),
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
}

/** The engine client for the signed-in user. Sends people without a session to the login page. */
export async function signedInEngine() {
  const token = await readSessionToken();
  if (!token) redirect("/login");
  const client = engineClient(token);
  const { data: me, response } = await client.GET("/me");
  // An expired or unknown token: the engine says 401 and the user signs in again.
  if (response.status === 401 || !me) redirect("/login");
  return { client, me };
}

/** The signed-in user, or null. Never redirects: used by the header on every page. */
export async function currentUser(): Promise<Me | null> {
  const token = await readSessionToken();
  if (!token) return null;
  try {
    const { data } = await engineClient(token).GET("/me");
    return data ?? null;
  } catch {
    return null; // engine unreachable: show "Sign in" rather than breaking every page
  }
}

export function can(me: Me, capability: string): boolean {
  // For showing or hiding controls only. The engine checks every request itself.
  return me.capabilities.includes(capability);
}

/** The engine's error message, or a plain fallback. Used to show why a write was refused. */
export function errorMessage(status: number, error: unknown, fallback: string): string {
  if (status === 403) return "You are not allowed to do this.";
  if (status === 409) return "This form was already sent with different details. Reload the page and try again.";
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : fallback;
}
