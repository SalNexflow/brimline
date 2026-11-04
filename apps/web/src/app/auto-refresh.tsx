"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ACTIVITY_EVENTS, IDLE_STOP_MS, quietSpell } from "@/lib/refresh";

/**
 * Re-renders the page every `everyMs` while `active`, so a planning run, a dispatched job or the
 * machines' connections show their progress. It asks nothing while the tab is hidden (Page
 * Visibility), and stops after `idleMs` without a click, key, wheel or touch, saying so; coming
 * back to the tab, focusing the window or any interaction refreshes at once and starts again.
 */
export function AutoRefresh({
  active,
  everyMs = 2000,
  idleMs = IDLE_STOP_MS,
}: {
  active: boolean;
  everyMs?: number;
  idleMs?: number;
}) {
  const router = useRouter();
  const [paused, setPaused] = useState(false);
  // When the page starts following something again (active went false, then true), start afresh:
  // a pause from before must not show while refreshing runs (React's "adjust state on a prop
  // change" pattern; fresh-context review).
  const [wasActive, setWasActive] = useState(active);
  if (active !== wasActive) {
    setWasActive(active);
    setPaused(false);
  }
  const resumeRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (!active) return;
    let timer: ReturnType<typeof setInterval> | undefined;
    let lastActivity = Date.now();

    const stop = () => {
      clearInterval(timer);
      timer = undefined;
    };
    const tick = () => {
      if (Date.now() - lastActivity >= idleMs) {
        stop();
        setPaused(true);
        return;
      }
      router.refresh();
    };
    const start = () => {
      if (timer === undefined && document.visibilityState === "visible") timer = setInterval(tick, everyMs);
    };
    // Someone is here: note it, and if refreshing had stopped, catch up at once and start again.
    const onActivity = () => {
      lastActivity = Date.now();
      if (timer !== undefined || document.visibilityState !== "visible") return;
      setPaused(false);
      router.refresh();
      start();
    };
    const onVisibility = () => (document.visibilityState === "visible" ? onActivity() : stop());

    resumeRef.current = onActivity;
    start();
    for (const e of ACTIVITY_EVENTS) window.addEventListener(e, onActivity, { passive: true, capture: true });
    window.addEventListener("focus", onActivity);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      for (const e of ACTIVITY_EVENTS) window.removeEventListener(e, onActivity, { capture: true });
      window.removeEventListener("focus", onActivity);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active, everyMs, idleMs, router]);

  if (!active) return null;
  // The live region is always in the page and only its content changes, so screen readers announce
  // the pause (a region added already filled is often not read out).
  return (
    <div role="status" className="refresh-paused">
      {paused ? (
        <p data-testid="refresh-paused">
          Auto-refresh paused after {quietSpell(idleMs)} without activity.{" "}
          <button type="button" className="link-button" onClick={() => resumeRef.current()}>
            Resume
          </button>
        </p>
      ) : null}
    </div>
  );
}
