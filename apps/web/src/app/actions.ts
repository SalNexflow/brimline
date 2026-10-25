"use server";

import { redirect } from "next/navigation";

import { engineClient } from "@/lib/engine";
import { clearSessionCookie, readSessionToken, writeSessionCookie } from "@/lib/session";

export async function signIn(formData: FormData): Promise<void> {
  const userCode = String(formData.get("user_code") ?? "");
  const { data } = await engineClient().POST("/auth/demo-login", {
    body: { user_code: userCode },
  });
  if (!data) redirect("/login?error=1");
  await writeSessionCookie(data.token, new Date(data.expires_at));
  redirect("/orders");
}

export async function signOut(): Promise<void> {
  const token = await readSessionToken();
  if (token) {
    // Revoke the token in the engine, not just in this browser, so a copied token stops working.
    // If the engine is unreachable the cookie is still cleared; the token then expires on time.
    await engineClient(token)
      .POST("/auth/logout")
      .catch(() => undefined);
  }
  await clearSessionCookie();
  redirect("/login");
}
