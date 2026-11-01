import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M12: the dispatcher proposes, a person presses Proceed, the agent's calls go through the guard, and a
// simulated machine starts. Runs on the real clock: a print may only start inside a shift (R10, checked
// by the guard's plan check), so outside shift hours the proposal is shown as refused instead.

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

/** Inside a staffed shift in the shop (Mon-Fri 08:00-17:00, Sat 09:00-13:00, Berlin), with a margin. */
function inShift(): boolean {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Berlin", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const minutes = Number(get("hour")) * 60 + Number(get("minute"));
  const day = get("weekday");
  if (["Mon", "Tue", "Wed", "Thu", "Fri"].includes(day)) return minutes >= 8 * 60 + 5 && minutes < 16 * 60 + 50;
  if (day === "Sat") return minutes >= 9 * 60 + 5 && minutes < 12 * 60 + 50;
  return false;
}

test("a dispatch goes from Proceed to a simulated start, through the guard", async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, "Priya Nandakumar", "planner");
  await page.goto("/board");
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible({ timeout: 180_000 });
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Approved plan", exact: true })).toBeVisible();

  // The operator finishes the chain guide's prep (the mill has no other job, so nothing collides).
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

  if (inShift()) {
    await proposal.check();
    await page.getByRole("button", { name: "Proceed" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Proceed recorded" })).toBeVisible();
    await expect(page.getByTestId("call-row").filter({ hasText: "start_task" })).toContainText("allowed");
    await expect(page.getByTestId("machine-CNC-1")).toContainText("Running");
  } else {
    await expect(proposal).toBeDisabled();
    await expect(page.getByText(/refused \(plan_check/)).toBeVisible();
  }
});

test("customers and office staff do not dispatch", async ({ page }) => {
  await signIn(page, "Sam Ortega", "staff");
  await page.goto("/dispatch");
  await expect(page.getByRole("status")).toContainText("does not dispatch work to machines");
});
