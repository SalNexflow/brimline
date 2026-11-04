import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// The theme switch (D199): System follows the device, Light and Dark override it, the choice is
// remembered in this browser and applied before the page is drawn. Text colour is the check: the
// light theme's ink is #1b1d2a, the dark theme's is #e9eaf4 (theme.css).

const INK_LIGHT = "rgb(27, 29, 42)";
const INK_DARK = "rgb(233, 234, 244)";

const ink = (page: Page) => page.evaluate(() => getComputedStyle(document.body).color);
// A person clicks the option's label (the radio button inside it is visually hidden).
const choice = (page: Page, name: string) =>
  page.getByRole("group", { name: "Colour theme" }).locator("label", { has: page.getByRole("radio", { name }) });

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("Light and Dark override the device, are remembered, and System follows it again", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/login");
  expect(await ink(page)).toBe(INK_LIGHT); // System, on a light device
  await expect(page.getByRole("radio", { name: "System" })).toBeChecked();

  await choice(page, "Dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await ink(page)).toBe(INK_DARK);
  await expectAccessible(page);

  // Remembered, and applied before the page is drawn: dark from the first frame after a reload.
  await page.reload();
  await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
  expect(await ink(page)).toBe(INK_DARK);

  // Signed in, on another page, the choice holds; Light on a dark device stays light.
  await page.getByRole("button", { name: "Sign in as Priya Nandakumar, planner" }).click();
  await expect(page).toHaveURL(/\/orders$/);
  expect(await ink(page)).toBe(INK_DARK);
  await page.emulateMedia({ colorScheme: "dark" });
  await choice(page, "Light").click();
  expect(await ink(page)).toBe(INK_LIGHT);
  await expectAccessible(page);

  // System hands it back to the device (dark here).
  await choice(page, "System").click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /./);
  expect(await ink(page)).toBe(INK_DARK);
});

test("the switch works by keyboard and fits a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/login");
  await page.getByRole("radio", { name: "System" }).focus();
  await page.keyboard.press("ArrowRight"); // radio buttons: arrows move and choose
  await expect(page.getByRole("radio", { name: "Light" })).toBeChecked();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Dark" })).toBeChecked();
  expect(await ink(page)).toBe(INK_DARK);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await expectAccessible(page);
});
