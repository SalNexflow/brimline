import { expect, test, type Page } from "@playwright/test";

// Reduced motion turns every animation and transition off (the browser tests run that way, see
// playwright.config.ts); with no preference, the same page does animate.

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in as Priya Nandakumar, planner" }).click();
  await expect(page.getByTestId("signed-in-as")).toContainText("Priya Nandakumar");
}

/** Running animations on the page, and the transition time of a button and the nav panel. */
async function motion(page: Page) {
  return page.evaluate(() => ({
    animations: document.getAnimations().length,
    button: getComputedStyle(document.querySelector("button")!).transitionDuration,
    panel: getComputedStyle(document.querySelector(".sidebar")!, "::after").transitionDuration,
  }));
}

test("with reduced motion nothing animates", async ({ page }) => {
  await signIn(page);
  await page.goto("/dispatch");
  await expect(page.getByRole("heading", { name: "Machines" })).toBeVisible();
  const m = await motion(page);
  expect(m.animations).toBe(0);
  expect(m.button.split(", ").every((d) => d === "0s")).toBe(true);
  expect(m.panel.split(", ").every((d) => d === "0s")).toBe(true);
});

test.describe("without that preference", () => {
  test.use({ contextOptions: { reducedMotion: "no-preference" } });

  test("the same page animates", async ({ page }) => {
    await signIn(page);
    await page.goto("/dispatch");
    await expect(page.getByRole("heading", { name: "Machines" })).toBeVisible();
    const m = await motion(page);
    expect(m.animations).toBeGreaterThan(0);
    expect(m.button).toContain("0.15s");
    expect(m.panel).toContain("0.22s");
  });
});
