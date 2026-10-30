"use client";

import { type ReactNode, useEffect, useState } from "react";

import { Waking } from "./waking";

// The free engine sleeps after 15 idle minutes. Checking every 5 minutes while the tab is visible
// keeps it awake for someone looking at the page; a hidden tab stops checking, so it can sleep.
export const CHECK_EVERY_MS = 5 * 60 * 1000;

/**
 * Hosted demo only. The layout's waking check runs on a full page load, not on clicks inside an
 * open page, so a tab left open past the engine's sleep made every click wait about a minute with
 * nothing on screen. This watches the open page and shows the waking screen as soon as the engine
 * is asleep: when the tab comes back into view, and every few minutes while it is visible.
 */
export function WakeWatch({ children }: { children: ReactNode }) {
  const [asleep, setAsleep] = useState(false);
  useEffect(() => {
    async function check() {
      if (document.visibilityState === "hidden") return;
      try {
        const r = await fetch("/engine-health", { cache: "no-store" });
        if (r.status === 503) setAsleep(true);
      } catch {
        // The browser itself is offline: not the engine's sleep, so leave the page as it is.
      }
    }
    const timer = setInterval(check, CHECK_EVERY_MS);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, []);
  return asleep ? <Waking /> : children;
}
