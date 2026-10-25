import "server-only";

import { cookies } from "next/headers";

import { SESSION_COOKIE, sessionCookieOptions } from "./cookie-options";

// The token is an opaque string signed by the engine. The web app stores and forwards it,
// and never decides anything from it: the engine verifies it on every request.

export async function readSessionToken(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

export async function writeSessionCookie(token: string, expiresAt: Date): Promise<void> {
  const production = process.env.NODE_ENV === "production";
  (await cookies()).set(SESSION_COOKIE, token, sessionCookieOptions(expiresAt, production));
}

export async function clearSessionCookie(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
}
