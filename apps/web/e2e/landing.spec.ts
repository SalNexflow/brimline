import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const SESSION_COOKIE_NAME = "brimline_session"; // lib/cookie-options.ts

// The front page (D202): before sign-in, static, three ways into the demo, and every demo protection
// left in front of the app. Signed-in people go straight to the app.

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 2).join(", ")}`)).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  for (const [size, viewport] of [["desktop", { width: 1280, height: 800 }], ["phone", { width: 390, height: 844 }]] as const) {
    test(`the front page reads well: ${size}, ${scheme}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByRole("note")).toContainText("all data are fictional");
      await expect(page.getByRole("button", { name: /^Try it as/ })).toHaveCount(3);
      await expectAccessible(page);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    });
  }
}

test("the page asks the engine nothing while you read it, and the video waits to be played", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/engine-health") asked.push(r.url());
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  expect(asked).toEqual([]); // only a hover or a press on Try it asks whether the engine is awake
  const video = page.locator("video");
  await expect(video).toHaveAttribute("controls", "");
  await expect(video).toHaveAttribute("preload", "none");
  expect(await video.evaluate((v: HTMLVideoElement) => [v.autoplay, v.paused])).toEqual([false, true]);
});

test("Try it as a planner signs in with the demo login, and the front page then leads into the app", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Try it as a planner/ }).click();
  await expect(page).toHaveURL(/\/orders$/);
  await expect(page.getByTestId("signed-in-as")).toContainText("Priya Nandakumar");
  await page.goto("/");
  await expect(page).toHaveURL(/\/orders$/); // signed in: straight into the app
});

test("with the engine asleep, Try it goes through the sign-in page, which waits for it", async ({ page }) => {
  await page.route("**/engine-health", (route) => route.fulfill({ status: 503, body: "asleep" }));
  await page.goto("/");
  await page.getByRole("button", { name: /Try it as an operator/ }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("a session the engine no longer accepts is forgotten, so the front page shows again", async ({ page, context }) => {
  // As after the demo's nightly reset: the browser still has a cookie, the engine refuses its token.
  await context.addCookies([{ name: SESSION_COOKIE_NAME, value: "a-token-from-before-the-reset", url: "http://localhost:3100" }]);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/); // sent into the app, refused, cookie cleared
  expect((await context.cookies()).map((c) => c.name)).not.toContain(SESSION_COOKIE_NAME);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("From a customer's message");
});
