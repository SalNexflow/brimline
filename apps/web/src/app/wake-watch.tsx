"use client";

import { type ReactNode, useEffect, useState } from "react";

import { ACTIVITY_EVENTS, IDLE_STOP_MS } from "@/lib/refresh";

import { Waking } from "./waking";

// The free engine sleeps after 15 idle minutes. Checking every 5 minutes while the tab is visible
// keeps it awake for someone using the page; a hidden tab, or one nobody has touched for
// IDLE_STOP_MS, stops checking, so the engine (and Neon's compute behind it) can sleep (D200).
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
    let lastActivity = Date.now();
    const onActivity = () => {
      const wasIdle = Date.now() - lastActivity >= IDLE_STOP_MS;
      lastActivity = Date.now();
      if (wasIdle) void check(); // back after a long pause: the engine may have slept meanwhile
    };
    async function check() {
      if (document.visibilityState === "hidden") return;
      if (Date.now() - lastActivity >= IDLE_STOP_MS) return; // nobody here: let it sleep
      try {
        const r = await fetch("/engine-health", { cache: "no-store" });
        if (r.status === 503) setAsleep(true);
      } catch {
        // The browser itself is offline: not the engine's sleep, so leave the page as it is.
      }
    }
    const timer = setInterval(check, CHECK_EVERY_MS);
    const onVisibility = () => {
      if (document.visibilityState === "visible") lastActivity = Date.now();
      void check();
    };
    document.addEventListener("visibilitychange", onVisibility);
    for (const e of ACTIVITY_EVENTS) window.addEventListener(e, onActivity, { passive: true, capture: true });
    window.addEventListener("focus", onActivity);
    return () => {
      window.removeEventListener("focus", onActivity);
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      for (const e of ACTIVITY_EVENTS) window.removeEventListener(e, onActivity, { capture: true });
    };
  }, []);
  return asleep ? <Waking /> : children;
}
