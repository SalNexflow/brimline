// When pages refresh themselves (D200), checked 2026-11-04. Every refresh asks the engine, and on the
// hosted demo the engine keeps Neon's compute awake (100 CU-hours a month on the Free plan), so a
// page nobody is looking at must stop asking.

/** No click, key, wheel or touch for this long: auto-refresh and the waking check stop until the
    person comes back. */
export const IDLE_STOP_MS = 10 * 60 * 1000;

/** What counts as someone using the page (window focus counts too, in each listener). Not "scroll":
    the browser fires it on its own when a refresh changes the content above the viewport, which
    would keep an unattended tab "active"; wheel, touch, keys and a scrollbar drag (pointerdown)
    cover a person scrolling (fresh-context review). */
export const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

/** "10 minutes", "45 seconds": for the paused notice. */
export function quietSpell(ms: number): string {
  if (ms >= 60_000) {
    const minutes = Math.round(ms / 60_000);
    return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  const seconds = Math.max(1, Math.round(ms / 1000));
  return `${seconds} second${seconds === 1 ? "" : "s"}`;
}
