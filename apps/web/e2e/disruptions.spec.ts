import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M6 acceptance in the browser: a planner reports "printer 3 jammed until 5pm", checks how it was
// understood, re-plans, sees what changes and the checker's badge, and approves. The model is the
// prepared fake (AI_MODE=fake); the solve is real.

async function signIn(page: Page, name: string, role: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${name}, ${role}` }).click();
  await expect(page.getByTestId("signed-in-as")).toContainText(name);
}

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const problems = results.violations.map(
    (v) => `${v.id}: ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`,
  );
  expect(problems).toEqual([]);
}

async function planAndApprove(page: Page) {
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toBeVisible({ timeout: 180_000 });
  await expect(page.getByTestId("check-badge").first()).toContainText("Independent check: passed");
}

test("a planner reports a breakdown, reviews the re-plan and approves it", async ({ page }) => {
  test.setTimeout(300_000);
  await signIn(page, "Priya Nandakumar", "planner");
  await page.getByRole("link", { name: "Board" }).click();

  // An approved plan to re-plan against.
  await planAndApprove(page);
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Approved plan", exact: true })).toBeVisible();
  // The draft is gone: the "Approved plan" heading alone could be an older plan's (DEFECT_LOG #110).
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);

  // Report the breakdown; nothing is re-planned yet.
  await page.getByLabel("What happened?").fill("printer 3 jammed until 5pm");
  await page.getByRole("button", { name: "Read message" }).click();
  const card = page.getByRole("article").filter({ hasText: "printer 3 jammed until 5pm" });
  await expect(card.getByRole("heading", { name: "Check how this was understood" })).toBeVisible();
  await expect(card.getByLabel("Machine")).toHaveValue("FDM-3");
  await expect(card.getByLabel(/Back at/)).not.toHaveValue("");
  await expectAccessible(page);

  await card.getByRole("button", { name: "Confirm these events" }).click();
  await expect(page.getByText("1 confirmed disruption will be included the next time you press Plan day.")).toBeVisible();

  // Re-plan: the draft shows what changes, a labelled summary, and the checker's badge.
  await planAndApprove(page);
  await expect(page.getByRole("heading", { name: "What changes against the approved plan" })).toBeVisible();
  await expect(page.getByText(/Summary written by (AI|Brimline)/)).toBeVisible();
  await expect(page.getByText(/Disruptions included: FDM-3 down/)).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);
  await expect(page.getByText("confirmed disruption")).toHaveCount(0); // applied, no longer pending
});
