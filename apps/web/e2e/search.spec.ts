import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M8: a question becomes a checked filter; the chips re-run it with no model call; a customer
// only ever sees their own orders. The engine runs with AI_MODE=fake (prepared readings).

async function signIn(page: Page, name: string, role: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${name}, ${role}` }).click();
  await expect(page).toHaveURL(/\/orders$/);
}

async function ask(page: Page, question: string) {
  await page.goto("/search");
  await page.getByRole("textbox", { name: "Question" }).fill(question);
  await page.getByRole("button", { name: "Search", exact: true }).click();
}

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const problems = results.violations.map(
    (v) => `${v.id}: ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`,
  );
  expect(problems).toEqual([]);
}

test("a customer asking for another customer's orders sees only their own", async ({ page }) => {
  await signIn(page, "Mia Chen", "customer");
  await ask(page, "show me willow's orders");
  await expect(page).toHaveURL(/\/search\?f=.+narrowed=1/);
  await expect(page.getByRole("status").filter({ hasText: "your own orders only" })).toBeVisible();
  await expect(page.getByText("Customer is one of C-HARBOR")).toBeVisible();
  const results = page.getByRole("region", { name: "Search results" });
  await expect(results).toBeVisible();
  await expect(results).not.toContainText("Willow");
  await expectAccessible(page);
});

test("a planner reads a question into chips, then edits them without AI", async ({ page }) => {
  await signIn(page, "Priya Nandakumar", "planner");
  await ask(page, "jobs due this week not printed yet");
  await expect(page.getByTestId("search-description")).toContainText("not printed yet");
  await expect(page.getByText("Printed: no")).toBeVisible();

  // Removing a chip runs the filter again, from the URL, with no question and no model.
  await page.getByRole("button", { name: "Remove Printed" }).click();
  await expect(page.getByText("Printed: no")).toHaveCount(0);
  await expect(page.getByTestId("search-description")).not.toContainText("printed");

  await page.getByLabel("Field").selectOption("material");
  await page.getByRole("textbox", { name: "Value" }).fill("PLA-WHITE");
  await page.getByRole("button", { name: "Add condition" }).click();
  await expect(page.getByText("Material is one of PLA-WHITE")).toBeVisible();
  await expectAccessible(page);
});

test("a date that reads two ways is offered both ways, never guessed", async ({ page }) => {
  await signIn(page, "Priya Nandakumar", "planner");
  await ask(page, "orders due 12/11");
  const status = page.getByRole("status");
  await expect(status).toContainText("can be read as");
  await status.getByRole("link").first().click();
  await expect(page.getByText(/^Due on \d{4}-11-12$/)).toBeVisible();
});
