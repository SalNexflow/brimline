import { expect, test } from "@playwright/test";

test("home page loads and shows the Brimline heading", async ({ page }) => {
  const response = await page.goto("/");

  expect(response?.status()).toBe(200);
  await expect(page).toHaveTitle("Brimline");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Brimline");
});
