import { expect, test, type Page } from "@playwright/test";

// The icon rail opens on hover or keyboard focus; a mouse click on a link must not leave it open
// over the page (DEFECT_LOG #109).

async function labelOpacity(page: Page, name: string): Promise<string> {
  return page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name, exact: true })
    .locator(".nav-label")
    .evaluate((el) => getComputedStyle(el).opacity);
}

test("the rail closes after a mouse click and opens for keyboard focus", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in as Priya Nandakumar, planner" }).click();
  await expect(page.getByTestId("signed-in-as")).toContainText("Priya Nandakumar");

  await page.getByRole("link", { name: "Board", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Production board", level: 1 })).toBeVisible();
  await page.mouse.move(1200, 700);
  expect(await labelOpacity(page, "Board")).toBe("0");

  await page.keyboard.press("Tab"); // from the clicked link to the next one, by keyboard
  await expect(page.getByRole("link", { name: "Queues", exact: true })).toBeFocused();
  expect(await labelOpacity(page, "Queues")).toBe("1");
});
