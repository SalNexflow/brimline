import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M9: the seeded TPU-BLACK shortage shows with what to order (code only; nothing is ordered), and
// staff record the order they placed. Runs on the real clock, so dates are not asserted here
// (the engine's tests check them by hand).

async function signIn(page: Page, name: string, role: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${name}, ${role}` }).click();
  await expect(page).toHaveURL(/\/orders$/);
}

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const problems = results.violations.map(
    (v) => `${v.id}: ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`,
  );
  expect(problems).toEqual([]);
}

test("the TPU-BLACK shortage shows with a suggestion, and staff record the order", async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, "Priya Nandakumar", "planner");
  await page.goto("/board");
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible({ timeout: 180_000 });
  await page.getByRole("link", { name: "Materials", exact: true }).click();
  const shortage = page.getByTestId("shortage-TPU-BLACK").first();
  await expect(shortage).toContainText("runs short");
  await expect(shortage).toContainText("BL-0005-2");
  await expect(page.getByTestId("suggestion-TPU-BLACK").first()).toContainText("from Quickspool Express");
  // Planners see it but do not record purchases.
  await expect(page.getByRole("form", { name: "Record a purchase order" })).toHaveCount(0);
  await expectAccessible(page);

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "Sam Ortega", "staff");
  await page.goto("/materials");
  const form = page.getByRole("form", { name: "Record a purchase order" });
  // Filled in from the suggestion; a person still checks it and presses the button.
  await expect(form.getByLabel("Material")).toHaveValue("TPU-BLACK");
  await expect(form.getByLabel("Supplier")).toHaveValue("Quickspool Express");
  const later = new Date(Date.now() + 3 * 86_400_000).toISOString().slice(0, 10);
  await form.getByLabel("Expected delivery (shop time)").fill(`${later}T10:00`);
  await expectAccessible(page);
  await form.getByRole("button", { name: "Record purchase order" }).click();
  await expect(page.getByRole("status").filter({ hasText: "recorded." })).toBeVisible();
  await expect(page.getByTestId("stock-TPU-BLACK")).toContainText("500 g");
});

test("operators and customers do not see materials", async ({ page }) => {
  await signIn(page, "Jonas Weber", "operator");
  await page.goto("/materials");
  await expect(page.getByRole("status")).toContainText("does not see the shop's stock");
});
