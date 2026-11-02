import { mkdirSync } from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// Design review shots (SHOWCASE=design): key screens at desktop and phone width, light and dark,
// written to docs/design/shots/. Never touches the README screenshots or the video. Each shot also
// runs the same axe checks as the browser tests and fails on any WCAG A or AA problem.

const OUT = path.resolve(__dirname, "..", "..", "..", "docs", "design", "shots");
const SCREENS = (process.env.DESIGN_SCREENS ?? "board,dispatch").split(",");
const SIZES = { desktop: { width: 1280, height: 800 }, phone: { width: 390, height: 844 } } as const;

async function signIn(page: Page, name: string, role: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${name}, ${role}` }).click();
  await expect(page.getByTestId("signed-in-as")).toContainText(name);
}

/** Motion is on in these shots: wait until every finite animation has finished. */
async function settled(page: Page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
}

async function axeProblems(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  return results.violations.map((v) => `${v.id}: ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
}

const PATHS: Record<string, string> = {
  board: "/board",
  dispatch: "/dispatch",
  orders: "/orders",
  "order-detail": "/orders/BL-0001",
  materials: "/materials",
  reports: "/reports",
  login: "/login",
};

for (const scheme of ["light", "dark"] as const) {
  test(`design shots, ${scheme}`, async ({ page }) => {
    mkdirSync(OUT, { recursive: true });
    await page.emulateMedia({ colorScheme: scheme });
    if (!SCREENS.every((s) => s === "login")) await signIn(page, "Priya Nandakumar", "planner");
    const problems: string[] = [];
    for (const screen of SCREENS) {
      for (const [size, viewport] of Object.entries(SIZES)) {
        if (scheme === "dark" && size === "phone") continue; // dark at desktop width is enough to judge
        await page.setViewportSize(viewport);
        await page.goto(PATHS[screen] ?? `/${screen}`);
        await page.waitForLoadState("networkidle");
        await settled(page);
        // The showcase pins the shop clock to Monday 10:00; the board's "now" line must read it.
        if (screen === "board") await expect(page.getByText(/^Now: Mon \d+ \w+, 10:00\./).first()).toBeAttached();
        await page.screenshot({ path: path.join(OUT, `${screen}-${size}-${scheme}.png`), fullPage: true });
        problems.push(...(await axeProblems(page)).map((p) => `${screen} ${size}: ${p}`));
      }
    }
    expect(problems).toEqual([]);
  });
}

// Dispatch with work in it: the same steps as the video's dispatch scene (replayed agent replies),
// then the screen after Proceed, with a proposal carried out and the tool-call log.
test("design shots, dispatch after Proceed", async ({ page }) => {
  if (!SCREENS.includes("dispatch")) test.skip();
  await signIn(page, "Jonas Weber", "operator");
  await page.goto("/queues");
  await page.getByRole("button", { name: /^Start: Prep for BL-0005 Chain guide/ }).click();
  await page.getByRole("button", { name: /^Done: Prep for BL-0005 Chain guide/ }).click();
  await signIn(page, "Priya Nandakumar", "planner");
  await page.goto("/dispatch");
  await page.getByRole("button", { name: "Ask the dispatcher" }).click();
  // The agent's replies are replayed from a recording; a code fallback here means the recording
  // no longer matches the prompt (the label must appear only when the AI budget is reached).
  await expect(page.getByTestId("latest-run")).not.toContainText("Proposed by code");
  const proposal = page.getByRole("checkbox", { name: /Start BL-0005-1 on CNC-1/ });
  await proposal.check();
  await page.getByRole("button", { name: "Proceed" }).click();
  await expect(page.getByTestId("call-row").filter({ hasText: "start_task" })).toContainText("allowed");
  await expect(page.getByTestId("call-row").filter({ hasText: "start_task" })).toContainText("agent");
  const problems: string[] = [];
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const [size, viewport] of Object.entries(SIZES)) {
      if (scheme === "dark" && size === "phone") continue;
      await page.setViewportSize(viewport);
      await settled(page);
      await page.screenshot({ path: path.join(OUT, `dispatch-run-${size}-${scheme}.png`), fullPage: true });
      problems.push(...(await axeProblems(page)).map((p) => `dispatch-run ${size} ${scheme}: ${p}`));
    }
  }
  expect(problems).toEqual([]);
});
