import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Stills of the real app for the product video (SHOWCASE=stills), written to video/public/stills/.
// The showcase stack: fictional shop, fake data, the shop clock pinned to Monday 10:00.

const OUT = path.resolve(__dirname, "..", "..", "..", "video", "public", "stills");

test.use({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });

async function settled(page: Page) {
  await page.mouse.move(1900, 1060); // off the icon rail, which opens on hover
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
}

test("video stills", async ({ page }) => {
  mkdirSync(OUT, { recursive: true });
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in as Priya Nandakumar, planner" }).click();
  await expect(page.getByTestId("signed-in-as")).toContainText("Priya Nandakumar");

  // Shot 8: the approved plan with its check badge and stat cards.
  await page.goto("/board");
  const approved = page.getByRole("heading", { name: "Approved plan", exact: true });
  await expect(approved).toBeVisible();
  await approved.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await settled(page);
  await page.screenshot({ path: path.join(OUT, "board-check.png") });
});
