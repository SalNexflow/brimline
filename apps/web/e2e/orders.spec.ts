import { expect, test, type Page } from "@playwright/test";

// Seeded data (config/shop.toml): BL-0001 and BL-0002 belong to Harbor Lane Robotics Club,
// BL-0003 to Willow Street Dental Lab. The database is reset before every run.
//
// Locators use roles with exact names: Next keeps recently visited pages mounted but hidden,
// and role locators ignore hidden elements while label and text locators do not.

const USERS = {
  staff: { name: "Sam Ortega", role: "staff" },
  planner: { name: "Priya Nandakumar", role: "planner" },
  operator: { name: "Jonas Weber", role: "operator" },
  customer: { name: "Mia Chen", role: "customer" },
} as const;

async function signIn(page: Page, user: (typeof USERS)[keyof typeof USERS]) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${user.name}, ${user.role}` }).click();
  await expect(page).toHaveURL(/\/orders$/);
  await expect(page.getByTestId("signed-in-as")).toContainText(user.name);
}

/** A due date two weeks from now, as the date input expects it (YYYY-MM-DD). */
function dueInTwoWeeks(): string {
  return new Date(Date.now() + 14 * 24 * 3600 * 1000).toISOString().slice(0, 10);
}

for (const user of Object.values(USERS)) {
  test(`${user.role} can sign in and see the order list`, async ({ page }) => {
    await signIn(page, user);
    await expect(page.getByTestId("signed-in-as")).toContainText(user.role);
    await expect(page.getByRole("heading", { name: "Orders", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "BL-0001" })).toBeVisible();
  });
}

test("staff create an order by hand and its audit row appears in History", async ({ page }) => {
  await signIn(page, USERS.staff);
  await page.getByRole("link", { name: "New order" }).click();

  await page.getByRole("combobox", { name: "Customer", exact: true }).selectOption({ label: "Willow Street Dental Lab" });
  await page.getByLabel("Due date", { exact: true }).fill(dueInTwoWeeks());
  await page.getByLabel("Line 1 part name").fill("Aligner case");
  await page.getByLabel("Line 1 quantity").fill("12");
  await page.getByLabel("Line 1 material").selectOption({ label: "Tough resin, clear" });
  await page.getByRole("button", { name: "Create order" }).click();

  await expect(page).toHaveURL(/\/orders\/BL-\d{4}$/);
  await expect(page.getByRole("cell", { name: "Aligner case" })).toBeVisible();

  const history = page.getByRole("region", { name: "History" });
  const row = history.getByRole("row").filter({ hasText: "order.create" });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Sam Ortega");
  // The request's idempotency key is recorded with the audit row.
  await expect(row.locator("code")).toHaveText(/^[0-9a-f-]{36}$/);
});

test("the form explains what is missing instead of sending a bad order", async ({ page }) => {
  await signIn(page, USERS.staff);
  await page.goto("/orders/new");
  await page.getByRole("combobox", { name: "Customer", exact: true }).selectOption({ label: "Harbor Lane Robotics Club" });
  await page.getByLabel("Due date", { exact: true }).fill(dueInTwoWeeks());
  await page.getByLabel("Line 1 part name").fill("Bracket");
  await page.getByLabel("Line 1 quantity").fill("3");
  await page.getByRole("button", { name: "Create order" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "Please fix" })).toContainText(
    "Every line needs a material",
  );
  await expect(page).toHaveURL(/\/orders\/new$/);
});

test("a customer sees only their own orders and no History", async ({ page }) => {
  await signIn(page, USERS.customer);
  await expect(page.getByRole("link", { name: "BL-0001" })).toBeVisible();
  await expect(page.getByRole("link", { name: "BL-0003" })).toHaveCount(0);

  // Another customer's order looks exactly like one that does not exist.
  await page.goto("/orders/BL-0003");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();

  await page.goto("/orders/BL-0001");
  await expect(page.getByRole("heading", { name: "Order BL-0001" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "History" })).toHaveCount(0);
});

test("a customer can create an order only for themselves", async ({ page }) => {
  await signIn(page, USERS.customer);
  await page.getByRole("link", { name: "New order" }).click();
  await expect(page.getByText("Ordering for Harbor Lane Robotics Club")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Customer", exact: true })).toHaveCount(0); // no way to pick someone else

  await page.getByLabel("Due date", { exact: true }).fill(dueInTwoWeeks());
  await page.getByLabel("Line 1 part name").fill("Bumper");
  await page.getByLabel("Line 1 quantity").fill("2");
  await page.getByLabel("Line 1 material").selectOption({ label: "TPU 95A, black" });
  await page.getByRole("button", { name: "Create order" }).click();

  await expect(page).toHaveURL(/\/orders\/BL-\d{4}$/);
  await expect(
    page.getByRole("definition").filter({ hasText: "Harbor Lane Robotics Club" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "History" })).toHaveCount(0);
});

test("a planner sees History; an operator does not, and neither can take orders", async ({
  page,
}) => {
  await signIn(page, USERS.planner);
  await expect(page.getByRole("link", { name: "New order" })).toHaveCount(0);
  await page.goto("/orders/BL-0001");
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, USERS.operator);
  await expect(page.getByRole("link", { name: "New order" })).toHaveCount(0);
  await page.goto("/orders/BL-0001");
  await expect(page.getByRole("heading", { name: "Order BL-0001" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "History" })).toHaveCount(0);
});

test("the session cookie is httpOnly and SameSite=Lax", async ({ page, context }) => {
  await signIn(page, USERS.staff);
  const cookie = (await context.cookies()).find((c) => c.name === "brimline_session");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Lax", path: "/" });
  // Page scripts cannot read it.
  expect(await page.evaluate(() => document.cookie)).not.toContain("brimline_session");
});

test("signed-out visitors are sent to the login page", async ({ page }) => {
  await page.goto("/orders");
  await expect(page).toHaveURL(/\/login$/);
});
