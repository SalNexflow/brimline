"use server";

import { redirect } from "next/navigation";

import { engineClient } from "@/lib/engine";
import { clearSessionCookie, writeSessionCookie } from "@/lib/session";

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
  await clearSessionCookie();
  redirect("/login");
}
