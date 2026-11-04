import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M12b: the Connectivity tab. The simulator's modes drive what it shows: "answers slowly" makes a
// machine slow, "stops answering" makes it unreachable. Test connection makes one status call now, so the
// test never waits for the engine's poller; each person may test a machine once every 10 s, so a planner
// and an operator test in turn. Every machine is set back to "works normally" at the end: the
// simulator keeps its modes for the whole run, and the dispatch test comes next.

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

const card = (page: Page, code: string) => page.getByTestId(`connectivity-${code}`);

async function setMode(page: Page, code: string, behaviour: string) {
  await page.goto("/connectivity");
  const c = card(page, code);
  await c.getByText(`Simulation settings for ${code}`).click();
  await c.getByLabel("Behaviour").selectOption({ label: behaviour });
  await c.getByRole("button", { name: "Set simulation" }).click();
  await expect(page.getByRole("status").filter({ hasText: `Simulation of ${code} changed` })).toBeVisible();
}

async function testNow(page: Page, code: string): Promise<string> {
  const c = card(page, code);
  await c.getByRole("button", { name: `Test connection to ${code}` }).click();
  const result = c.getByTestId("test-result");
  await expect(result).toBeVisible({ timeout: 15_000 });
  return result.innerText();
}

async function asOperatorTest(page: Page, code: string): Promise<string> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "Jonas Weber", "operator");
  await page.goto("/connectivity");
  const said = await testNow(page, code);
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, "Priya Nandakumar", "planner");
  await page.goto("/connectivity");
  return said;
}

test("each simulated mode shows as its connection state, through Test connection", async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page, "Priya Nandakumar", "planner");
  await page.goto("/connectivity");
  await expect(page.getByTestId("simulated-notice")).toContainText("Untested on real hardware");
  await expect(page.locator("[data-testid^=connectivity-]")).toHaveCount(6);
  await expect(card(page, "FDM-1").getByText("simulated", { exact: true })).toBeVisible();
  try {
    // Works normally: connected, answered in milliseconds.
    expect(await testNow(page, "FDM-1")).toMatch(/^FDM-1 answered in (\d+ ms|under 1 ms) \(idle\)\.$/);
    await expect(card(page, "FDM-1").getByTestId("connection-state")).toContainText("Connected");

    // Answers slowly (1 s late): two slow answers out of the last three make the median slow.
    await setMode(page, "FDM-3", "Answers slowly");
    expect(await testNow(page, "FDM-3")).toMatch(/^FDM-3 answered in (1\d{3}|[2-9]\d{3}) ms/);
    await asOperatorTest(page, "FDM-3");
    await expect(card(page, "FDM-3").getByTestId("connection-state")).toContainText("Slow");
    await expect(card(page, "FDM-3")).toContainText("answers slowly");

    // Stops answering: two polls in a row without an answer make it unreachable.
    await setMode(page, "RESIN-1", "Stops answering");
    expect(await testNow(page, "RESIN-1")).toMatch(/^RESIN-1 did not answer usably/);
    await asOperatorTest(page, "RESIN-1");
    const resin = card(page, "RESIN-1");
    await expect(resin.getByTestId("connection-state")).toContainText("Unreachable");
    await expect(resin.getByTestId("last-error")).toContainText("timeout");
    await expect(resin.getByTestId("poll-strip")).toHaveAttribute("aria-label", /no answer/);

    // Refuses to start: it still answers every status call, so it stays connected (a fault would
    // show once a start is refused; the engine tests cover that).
    await setMode(page, "FDM-2", "Refuses to start");
    expect(await testNow(page, "FDM-2")).toMatch(/^FDM-2 answered in/);
    await expect(card(page, "FDM-2").getByTestId("connection-state")).toContainText("Connected");
    await expect(card(page, "FDM-2")).toContainText("refuses to start");

    // A second test of the same machine by the same person within 10 s is refused, kindly.
    await card(page, "FDM-2").getByRole("button", { name: "Test connection to FDM-2" }).click();
    await expect(card(page, "FDM-2").getByRole("alert")).toContainText("tested a moment ago");

    await expectAccessible(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.reload();
    await expect(page.locator("[data-testid^=connectivity-]")).toHaveCount(6);
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(375); // no sideways scrolling on a phone
    await expectAccessible(page);
  } finally {
    await page.setViewportSize({ width: 1280, height: 720 });
    for (const code of ["FDM-2", "FDM-3", "RESIN-1"]) await setMode(page, code, "Works normally");
  }
});

test("dispatch's machine cards link to their connection", async ({ page }) => {
  await signIn(page, "Jonas Weber", "operator");
  await page.goto("/dispatch");
  await page.getByTestId("connection-link-CNC-1").click();
  await expect(page).toHaveURL(/\/connectivity#machine-CNC-1$/);
  await expect(card(page, "CNC-1")).toBeVisible();
  // Operators test but do not change the simulation.
  await expect(card(page, "CNC-1").getByRole("button", { name: "Test connection to CNC-1" })).toBeVisible();
  await expect(page.getByText("Simulation settings for CNC-1")).toHaveCount(0);
});

for (const [name, role] of [["Sam Ortega", "staff"], ["Mia Chen", "customer"]] as const) {
  test(`a ${role} user does not see the connections`, async ({ page }) => {
    await signIn(page, name, role);
    await page.goto("/connectivity");
    await expect(page.getByRole("status")).toContainText("does not see the machines");
    await expect(page.locator("[data-testid^=connectivity-]")).toHaveCount(0);
  });
}
