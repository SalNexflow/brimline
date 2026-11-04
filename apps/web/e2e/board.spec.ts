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

/** An approved plan to look at: the one the test above approved, or a new one. */
async function approvedPlan(page: Page) {
  await page.goto("/board");
  if ((await page.getByRole("heading", { name: "Approved plan", exact: true }).count()) > 0) return;
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("button", { name: "Approve plan" })).toBeVisible({ timeout: 180_000 });
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Approved plan", exact: true })).toBeVisible();
  // The draft is gone: the "Approved plan" heading alone could be an older plan's (DEFECT_LOG #110).
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);
}

for (const [size, viewport] of [
  ["desktop", { width: 1280, height: 800 }],
  ["phone", { width: 390, height: 844 }],
] as const) {
  test(`the timeline draws three readable days and points to later work (${size})`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(viewport);
    await signIn(page, "Priya Nandakumar", "planner");
    await approvedPlan(page);
    const timeline = page.getByRole("region", { name: "Plan timeline (scrolls sideways)" }).last();

    // Three days drawn. Every planned task is either a bar or counted by its row's "later" marker,
    // which points to the table (a hand-made plan with later work is in schedule-view.test.tsx).
    await expect(timeline.locator(".day-label")).toHaveCount(3);
    const rows = await page.locator("section.schedule").last().locator(".plan-table tbody tr").count();
    const bars = await timeline.locator(".bar").count();
    const markers = timeline.locator("[data-testid^='later-']");
    const number = (t: string, re: RegExp) => Number(re.exec(t)?.[1] ?? 0);
    const counted = (await markers.allTextContents()).reduce((n, t) => n + number(t, /(\d+) earlier/) + number(t, /\+(\d+) later/), 0);
    expect(bars + counted).toBe(rows);
    for (const marker of await markers.all()) {
      await expect(marker).toHaveAttribute("href", /^#table-\d+$/);
      await expect(marker).toHaveAccessibleName(/^(\d+ earlier|\+\d+ later|\d+ earlier, \+\d+ later): .+ on .+, listed in the table$/);
    }

    // An hour is wide enough to read: the widest machine bar shows its whole label.
    const widest = await timeline.locator(".bar-machine .bar-text").evaluateAll((spans) =>
      Math.max(...spans.map((s) => (s.scrollWidth <= s.clientWidth ? s.clientWidth : 0))),
    );
    expect(widest).toBeGreaterThan(40);

    // Full details on hover, in the same words as the bar's accessible name.
    const bar = timeline.locator(".bar-machine").first();
    await bar.hover();
    const tip = await bar.evaluate((el) => {
      const after = getComputedStyle(el, "::after");
      return { text: after.content, opacity: after.opacity, name: el.getAttribute("aria-label") };
    });
    expect(tip.opacity).toBe("1");
    expect(tip.text).toBe(JSON.stringify(tip.name));

    // The page itself never scrolls sideways; only the timeline's own box does.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expectAccessible(page);

    // The whole plan, when it runs past three days: more days, nothing left to mark as later.
    const whole = page.getByRole("link", { name: /^Whole plan \(\d+ days\)$/ });
    if ((await whole.count()) > 0) {
      await whole.click();
      await expect(page).toHaveURL(/span=all/);
      expect(await timeline.locator(".day-label").count()).toBeGreaterThan(3);
      await expect(timeline.locator("[data-testid^='later-']")).toHaveCount(0);
      expect(await timeline.locator(".bar").count()).toBe(rows);
    } else {
      expect(counted).toBe(0);
    }
    await expectAccessible(page);
  });
}
