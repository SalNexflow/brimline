import { expect, test } from "@playwright/test";

test("home page loads and shows the Brimline heading", async ({ page }) => {
  const response = await page.goto("/");

  expect(response?.status()).toBe(200);
  await expect(page).toHaveTitle("Brimline");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Brimline");
});

test("the Brimline mark is the favicon and app icon, in every size (D201)", async ({ page, request }) => {
  await page.goto("/");
  const sizes = await page.locator('link[rel="icon"]').evaluateAll((ls) => ls.map((l) => l.getAttribute("sizes")));
  expect(sizes).toEqual(expect.arrayContaining(["16x16", "32x32", "512x512"]));
  await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveAttribute("sizes", "180x180");
  for (const href of await page.locator('link[rel="icon"], link[rel="apple-touch-icon"]').evaluateAll((ls) => ls.map((l) => l.getAttribute("href")))) {
    const r = await request.get(href!);
    expect(r.status(), href!).toBe(200);
  }
  expect((await request.get("/favicon.ico")).status()).toBe(200);
  expect((await request.get("/brand/mark.png")).status()).toBe(200);
});
