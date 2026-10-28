"use client";

import { useEffect, useState } from "react";

/** Shown while the free-tier engine wakes up (about a minute). Retries on its own. */
export function Waking() {
  const [tries, setTries] = useState(0);
  useEffect(() => {
    const timer = setInterval(async () => {
      setTries((n) => n + 1);
      try {
        const r = await fetch("/engine-health", { cache: "no-store" });
        if (r.ok) window.location.reload();
      } catch {
        // still asleep: try again on the next tick
      }
    }, 5000);
    return () => clearInterval(timer);
  }, []);
  return (
    <main className="page">
      <h1>The demo is waking up</h1>
      <p role="status">
        Brimline&apos;s engine runs on free hosting, which sleeps when nobody uses it. Waking it takes about a minute;
        this page checks every 5 seconds and opens by itself{tries > 0 ? ` (checked ${tries} time${tries === 1 ? "" : "s"})` : ""}.
      </p>
      <button type="button" onClick={() => window.location.reload()}>
        Try now
      </button>
    </main>
  );
}
