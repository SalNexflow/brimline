import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M10: an operator records why an attempt failed; the office sees quoted versus actual, with the
// seeded (synthetic, labelled) history flagging the one under-quoted material.

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

test("an operator records a failure with its reason", async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, "Priya Nandakumar", "planner");
  await page.goto("/board");
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible({ timeout: 180_000 });
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Approved plan", exact: true })).toBeVisible();
  // The draft is gone: the "Approved plan" heading alone could be an older plan's (DEFECT_LOG #110).
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "Jonas Weber", "operator");
  await page.goto("/queues");
  const start = page.getByRole("button", { name: /^Start: Prep for / }).first();
  const name = ((await start.getAttribute("aria-label")) ?? "").replace("Start: ", "");
  await start.click();
  // The row of the task just started: another test may have left a task running (the dispatch test
  // starts a machine job when the real clock is inside a shift), with its own "Failed…".
  const row = page.getByRole("row").filter({ has: page.getByRole("button", { name: `Done: ${name}` }) });
  await row.getByText("Failed…").click();
  // Without a reason the form does not go (the engine would refuse it too).
  await page.getByRole("button", { name: `Record failure: ${name}` }).click();
  await expect(page.getByRole("button", { name: `Record failure: ${name}` })).toBeVisible();
  await row.getByLabel("Why did it fail?").selectOption("bed_adhesion");
  await row.getByLabel("Note (optional)").fill("came loose at layer 3");
  await expectAccessible(page);
  await page.getByRole("button", { name: `Record failure: ${name}` }).click();
  await expect(page.getByRole("status")).toContainText(`${name}: failed.`);
});

test("the office sees quoted versus actual and the flagged material", async ({ page }) => {
  await signIn(page, "Sam Ortega", "staff");
  await page.getByRole("link", { name: "Reports" }).click();
  await expect(page.getByRole("heading", { name: "Quoted versus actual", level: 1 })).toBeVisible();
  // The seeded history is made up, and the page says so.
  await expect(page.getByTestId("synthetic-note")).toContainText("Synthetic history");
  await expect(page.getByRole("cell", { name: /History TPU-BLACK #1 synthetic/ })).toBeVisible();
  // Exactly one material is flagged, with a suggestion that links to the prices (nothing changes by itself).
  const flag = page.getByTestId("flag-TPU-BLACK");
  await expect(flag).toContainText("of 8 jobs cost more than 15 % over their quote");
  await expect(flag.getByRole("link", { name: "Review the price rule for TPU-BLACK." })).toHaveAttribute("href", "/price-rules");
  await expect(page.locator("[data-testid^=flag-]")).toHaveCount(1);
  await expectAccessible(page);
});

test("operators and customers do not see the report", async ({ page }) => {
  await signIn(page, "Jonas Weber", "operator");
  await page.goto("/reports");
  await expect(page.getByRole("status")).toContainText("does not see the shop's reports");
});
