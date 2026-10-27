import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M5 acceptance: a planner plans the day and approves it, and an operator completes a job.
// The engine plans for real here (CP-SAT, the full time limit), against the seeded orders.
// BL-0003 has one line, the resin model tray: prep, a machine run, then check and pack.

async function signIn(page: Page, name: string, role: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${name}, ${role}` }).click();
  await expect(page.getByTestId("signed-in-as")).toContainText(name);
}

/** No WCAG 2.1 A or AA problems that axe can detect on the current page. */
async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const problems = results.violations.map(
    (v) => `${v.id}: ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`,
  );
  expect(problems).toEqual([]);
}

test("a planner plans the day and approves it; an operator completes a job", async ({ page }) => {
  test.setTimeout(240_000); // the solve runs in the background for up to its quality limit

  await signIn(page, "Priya Nandakumar", "planner");
  await page.getByRole("link", { name: "Board" }).click();
  await expect(page.getByRole("heading", { name: "Production board", level: 1 })).toBeVisible();

  await page.getByRole("button", { name: "Plan day" }).click();
  // The board stays usable while the plan is made, then shows the draft with its badge.
  const draft = page.getByRole("heading", { name: "Draft plan, waiting for approval" });
  await expect(draft).toBeVisible({ timeout: 180_000 });
  const badge = page.getByTestId("check-badge");
  await expect(badge).toContainText("Independent check: passed");
  await expect(page.getByText("BL-0008-2 Prop sword hilt: missing part size")).toBeVisible();
  await expectAccessible(page);

  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Approved plan", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "Jonas Weber", "operator");
  await page.getByRole("link", { name: "Queues" }).click();
  await expect(page.getByRole("heading", { name: "Queues", level: 1 })).toBeVisible();
  await expectAccessible(page);

  for (const task of ["Prep", "Machine run", "Check and pack"]) {
    const name = `${task} for BL-0003 Model tray`;
    await page.getByRole("button", { name: `Start: ${name}` }).click();
    await page.getByRole("button", { name: `Done: ${name}` }).click();
    await expect(page.getByRole("button", { name: `Done: ${name}` })).toHaveCount(0);
  }
  await expect(page.getByTestId("task-BL-0003-1-finish")).toContainText("Done");

  // The job was the order's only line, so the order is done too.
  await page.getByRole("link", { name: "Orders" }).click();
  await expect(page.getByRole("row", { name: /BL-0003/ })).toContainText("done");
});
