import { expect, test, type Page } from "@playwright/test";

// Auto-refresh (D200), on the Connectivity page (every 5 s; the board and Dispatch use the same
// component): it asks nothing while the tab is hidden, stops after 10 minutes without activity with a
// "paused, click to resume" notice, and resumes on interaction. The browser's clock is faked, so ten
// minutes pass in a moment; a refresh is counted as one request for the page's server data (RSC).

async function openConnectivity(page: Page): Promise<() => number> {
  await page.clock.install();
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in as Priya Nandakumar, planner" }).click();
  await expect(page).toHaveURL(/\/orders$/);
  await page.goto("/connectivity");
  await expect(page.getByTestId("connectivity-FDM-1")).toBeVisible();
  let refreshes = 0;
  page.on("request", (r) => {
    // A refresh, not Next.js prefetching a link to this page (the nav rail does; found on the live demo).
    const h = r.headers();
    if (h["rsc"] === "1" && !h["next-router-prefetch"] && new URL(r.url()).pathname === "/connectivity") refreshes += 1;
  });
  return () => refreshes;
}

async function setVisibility(page: Page, state: "hidden" | "visible") {
  await page.evaluate((s) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => s });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => s === "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

test("a hidden tab asks nothing, and catches up as soon as it is seen again", async ({ page }) => {
  const refreshes = await openConnectivity(page);
  await page.clock.runFor(16_000);
  await expect.poll(refreshes).toBeGreaterThanOrEqual(3); // every 5 s while visible

  await setVisibility(page, "hidden");
  await page.waitForTimeout(500); // a refresh sent just before hiding is counted before we start
  const before = refreshes();
  await page.clock.runFor(120_000); // two minutes in a background tab
  await page.waitForTimeout(500); // real time for any request that was about to go out
  expect(refreshes()).toBe(before);

  await setVisibility(page, "visible");
  await expect.poll(refreshes).toBe(before + 1); // at once, not on the next tick
  await page.clock.runFor(5_000);
  await expect.poll(refreshes).toBe(before + 2); // and then on its schedule again
  await expect(page.getByTestId("refresh-paused")).toHaveCount(0);
});

test("ten minutes without activity stop refreshing, with a notice that resumes it", async ({ page }) => {
  const refreshes = await openConnectivity(page);
  await page.clock.fastForward("10:05"); // nobody touches the page for ten minutes and five seconds
  const notice = page.getByTestId("refresh-paused");
  await expect(notice).toHaveText("Auto-refresh paused after 10 minutes without activity. Resume");

  await page.waitForTimeout(500);
  const before = refreshes();
  await page.clock.runFor(60_000);
  await page.waitForTimeout(500);
  expect(refreshes()).toBe(before); // stopped: nothing for another minute

  await notice.getByRole("button", { name: "Resume" }).click();
  await expect(notice).toHaveCount(0);
  await expect.poll(refreshes).toBe(before + 1); // refreshed at once on coming back
  await page.clock.runFor(5_000);
  await expect.poll(refreshes).toBe(before + 2);
});
