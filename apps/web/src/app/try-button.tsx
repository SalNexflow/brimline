"use client";

import { useRouter } from "next/navigation";
import { useState, type MouseEvent } from "react";

/** One "Try it" button. The front page never waits for the engine, but signing in does: on the hosted
    demo the free engine may be asleep, and a sign-in sent then would hang. So the press first asks
    whether it is awake (a cheap health check, also sent on hover or focus to start it waking): awake,
    the form signs in as usual; asleep, the visitor goes to the sign-in page, which shows the "waking
    up" screen and opens by itself. Without script, the form simply submits. */
export function TryButton({ role, name }: { role: string; name: string }) {
  const router = useRouter();
  const [checking, setChecking] = useState(false);
  const warm = () => {
    void fetch("/engine-health", { cache: "no-store" }).catch(() => undefined);
  };
  async function onClick(e: MouseEvent<HTMLButtonElement>) {
    e.preventDefault();
    const form = e.currentTarget.form;
    setChecking(true);
    let awake = false;
    try {
      awake = (await fetch("/engine-health", { cache: "no-store", signal: AbortSignal.timeout(5000) })).ok;
    } catch {
      awake = false;
    }
    if (awake) {
      form?.requestSubmit();
    } else {
      setChecking(false); // ready again if the visitor comes back to this page
      router.push("/login");
    }
  }
  return (
    <button
      type="submit"
      className="try-button"
      disabled={checking}
      onClick={onClick}
      onPointerEnter={warm}
      onFocus={warm}
    >
      <span className="try-role">Try it as {/^[aeiou]/.test(role) ? "an" : "a"} {role}</span>
      <span className="try-name">{checking ? "Opening the demo…" : name}</span>
    </button>
  );
}
