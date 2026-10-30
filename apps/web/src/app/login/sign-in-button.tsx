"use client";

import type { ReactNode } from "react";
import { useFormStatus } from "react-dom";

/** A demo user's sign-in button that says it is working, so a slow engine never looks like a dead click. */
export function SignInButton({ label, children }: { label: string; children: ReactNode }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" aria-label={label} disabled={pending} aria-busy={pending}>
      {children}
      {pending ? <span className="muted">Signing in…</span> : null}
    </button>
  );
}
