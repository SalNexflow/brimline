import "server-only";

import { createHash } from "node:crypto";
import { headers } from "next/headers";

// The hosted demo (M11). Locally none of this is set and nothing changes.
//   ENGINE_WEB_KEY  sent on every engine call, so only this web app can call the engine;
//   X-Visitor       a keyed hash of the visitor's address (never the address), which the engine
//                   uses for its per-visitor model limit;
//   DEMO_WAKE_CHECK when "1", pages first check the engine is awake (free hosting sleeps).

export async function engineHeaders(): Promise<Record<string, string>> {
  const key = process.env.ENGINE_WEB_KEY;
  if (!key) return {};
  const h = await headers();
  // Vercel sets x-real-ip itself (a client cannot choose it); the forwarded chain is a fallback.
  // On another host, check which header its proxy sets before relying on this (docs/SECURITY.md).
  const address = h.get("x-real-ip") || (h.get("x-forwarded-for") ?? "").split(",")[0]?.trim() || "unknown";
  const visitor = createHash("sha256").update(`${key}|${address}`).digest("hex").slice(0, 16);
  return { "X-Engine-Key": key, "X-Visitor": visitor };
}

/** True when the engine answers its health check quickly. Only asked on the hosted demo. */
export async function engineAwake(): Promise<boolean> {
  if (process.env.DEMO_WAKE_CHECK !== "1") return true;
  try {
    const r = await fetch(`${process.env.ENGINE_URL}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    return r.ok;
  } catch {
    return false;
  }
}
