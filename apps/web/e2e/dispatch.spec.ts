import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M12: the dispatcher proposes, a person presses Proceed, the agent's calls go through the guard, and a
// simulated machine starts. A print may only start inside a shift (R10, checked by the guard's plan check).
// The shop clock is pinned (playwright.config.ts): the main run is inside a shift, and the @off-shift test
// runs on its own, outside one, where the same proposal is shown as refused.

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

/** An approved plan, the chain guide's prep done by the operator (the mill has no other job, so nothing
 * collides), and the dispatcher asked. Returns the proposal to start the chain guide on CNC-1. */
async function askDispatcher(page: Page) {
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
  await page.getByRole("button", { name: /^Start: Prep for BL-0005 Chain guide/ }).click();
  await page.getByRole("button", { name: /^Done: Prep for BL-0005 Chain guide/ }).click();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "Priya Nandakumar", "planner");
  await page.getByRole("link", { name: "Dispatch", exact: true }).click();
  await expect(page.getByTestId("simulated-notice")).toContainText("Untested on real hardware");
  await expect(page.getByTestId("machine-FDM-4")).toContainText("community-documented protocol");
  await expect(page.getByTestId("machine-CNC-1")).toContainText("Idle");
  await page.getByRole("button", { name: "Ask the dispatcher" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Nothing has reached a machine yet" })).toBeVisible();
  const proposal = page.getByRole("checkbox", { name: /Start BL-0005-1 on CNC-1/ });
  await expect(proposal).toBeVisible();
  await expectAccessible(page);
  return proposal;
}

test("a dispatch goes from Proceed to a simulated start, through the guard", async ({ page }) => {
  test.setTimeout(240_000);
  const proposal = await askDispatcher(page);
  await proposal.check();
  await page.getByRole("button", { name: "Proceed" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Proceed recorded" })).toBeVisible();
  await expect(page.getByTestId("call-row").filter({ hasText: "start_task" })).toContainText("allowed");
  await expect(page.getByTestId("machine-CNC-1")).toContainText("Running");

  // The watcher records the job the machine finishes (3 h of machining, about 18 s at the simulation's
  // speed). Waiting for it also leaves no running work behind: a running task that finishes later makes
  // the next test's draft plan stale (DEFECT_LOG #110).
  await page.goto("/queues");
  await expect(async () => {
    await page.reload();
    await expect(page.getByTestId("task-BL-0005-1-machine")).toContainText("Done", { timeout: 1_000 });
  }).toPass({ timeout: 90_000 });
});

test("outside a shift the same proposal is refused by the plan check @off-shift", async ({ page }) => {
  test.setTimeout(240_000);
  const proposal = await askDispatcher(page);
  await expect(proposal).toBeDisabled();
  await expect(page.getByText(/refused \(plan_check/)).toBeVisible();
});

test("customers and office staff do not dispatch", async ({ page }) => {
  await signIn(page, "Sam Ortega", "staff");
  await page.goto("/dispatch");
  await expect(page.getByRole("status")).toContainText("does not dispatch work to machines");
});
