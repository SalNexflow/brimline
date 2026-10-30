import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { CHECK_EVERY_MS, WakeWatch } from "./wake-watch";

// A page left open while the free engine went to sleep: clicks waited about a minute with nothing
// on screen, because the layout's waking check runs only on a full page load (DEFECT_LOG #82).

let engineAwake = true;

beforeEach(() => {
  vi.useFakeTimers();
  engineAwake = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(engineAwake ? "awake" : "asleep", { status: engineAwake ? 200 : 503 })),
  );
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function page() {
  return render(
    <WakeWatch>
      <p>Orders page</p>
    </WakeWatch>,
  );
}

test("an awake engine leaves the page alone", async () => {
  page();
  await act(() => vi.advanceTimersByTimeAsync(CHECK_EVERY_MS));
  expect(screen.getByText("Orders page")).toBeDefined();
});

test("an engine that fell asleep while the page was open shows the waking screen", async () => {
  page();
  engineAwake = false;
  await act(() => vi.advanceTimersByTimeAsync(CHECK_EVERY_MS));
  expect(screen.getByText("The demo is waking up")).toBeDefined();
  expect(screen.queryByText("Orders page")).toBeNull();
});

test("coming back to the tab checks at once, not on the next tick", async () => {
  page();
  engineAwake = false;
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByText("The demo is waking up")).toBeDefined();
});
