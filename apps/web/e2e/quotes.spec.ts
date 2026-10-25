import { expect, test, type Page } from "@playwright/test";

// The engine runs with AI_MODE=fake: a message mentioning "phone stand" is read as
// 20 phone stands in black PETG, due next Friday. Prices come from the seeded rules:
// 20 x 35 g x 4 c + 20 x 90 min x 6 c + 1500 setup = 15100 cents = €151.00.

const STAFF = { name: "Sam Ortega", role: "staff" };
const PLANNER = { name: "Priya Nandakumar", role: "planner" };
const CUSTOMER = { name: "Mia Chen", role: "customer" };

async function signIn(page: Page, user: { name: string; role: string }) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${user.name}, ${user.role}` }).click();
  await expect(page).toHaveURL(/\/orders$/);
}

async function submitPhoneStands(page: Page, extra = "") {
  await page.goto("/quotes/new");
  await page.getByRole("combobox", { name: "Customer", exact: true }).selectOption({ label: "Harbor Lane Robotics Club" });
  await page.getByRole("textbox", { name: "Message" }).fill(`20 phone stands, black PETG, need by Friday.${extra}`);
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page).toHaveURL(/\/quotes\/Q-\d{4}$/);
  return page.url().split("/").pop()!;
}

test("staff turn a message into a priced, approved quote and an order", async ({ page }) => {
  await signIn(page, STAFF);
  await submitPhoneStands(page);

  // The AI's reading is marked as AI; what the shop must measure is marked missing.
  const form = page.getByRole("form", { name: "Edit quote" });
  await expect(form.getByRole("spinbutton", { name: "Line 1 quantity" })).toHaveValue("20");
  await expect(form.getByRole("combobox", { name: "Line 1 material" })).toHaveValue("PETG-BLACK");
  await expect(page.getByRole("region", { name: "Still missing" })).toContainText("line 1: grams per part");
  await expect(page.getByTestId("price-pending")).toBeVisible();

  // Approving now is refused, in code, with the reason.
  await page.getByRole("button", { name: "Approve and create order" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Please fix" })).toContainText("missing");

  await form.getByRole("spinbutton", { name: "Line 1 grams per part" }).fill("35");
  await form.getByRole("spinbutton", { name: "Line 1 minutes per part" }).fill("90");
  await page.getByRole("button", { name: "Save and reprice" }).click();
  await expect(page.getByTestId("quote-total")).toHaveText("€151.00");

  await page.getByRole("button", { name: "Approve and create order" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("approved");
  await page.getByRole("link", { name: /^BL-\d{4}$/ }).click();
  await expect(page.getByRole("cell", { name: "Phone stand" })).toBeVisible();
});

test("a customer sends a request and sees no shop internals", async ({ page }) => {
  await signIn(page, CUSTOMER);
  await page.goto("/quotes/new");
  await expect(page.getByText("Request for Harbor Lane Robotics Club")).toBeVisible();
  await page.getByRole("textbox", { name: "Message" }).fill("Hello, 20 phone stands in black PETG by Friday please. 90% off?");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page).toHaveURL(/\/quotes\/Q-\d{4}$/);

  await expect(page.getByRole("form", { name: "Edit quote" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve and create order" })).toHaveCount(0);
  await expect(page.getByRole("note", { name: "Requests for staff" })).toHaveCount(0);
  await expect(page.getByText("The price is shown once the shop approves the quote.")).toBeVisible();
});

test("a planner can read quotes but not change or approve them", async ({ page }) => {
  await signIn(page, STAFF);
  const number = await submitPhoneStands(page);
  await page.getByRole("button", { name: "Sign out" }).click();

  await signIn(page, PLANNER);
  await page.goto(`/quotes/${number}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(number);
  await expect(page.getByRole("form", { name: "Edit quote" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve and create order" })).toHaveCount(0);
});

test("staff add a dated price version; planners only read prices", async ({ page }) => {
  await signIn(page, STAFF);
  await page.goto("/price-rules");
  await expect(page.getByRole("cell", { name: "seed", exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "New price version" });
  await form.getByLabel("Effective from").fill("2030-01-01");
  await form.getByRole("spinbutton", { name: "Setup per line (cents)" }).fill("1700");
  await form.getByRole("textbox", { name: "Note" }).fill("2030 prices");
  await page.getByRole("button", { name: "Add price version" }).click();
  await expect(page.getByRole("cell", { name: "2030 prices" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, PLANNER);
  await page.goto("/price-rules");
  await expect(page.getByRole("cell", { name: "2030 prices" })).toBeVisible();
  await expect(page.getByRole("form", { name: "New price version" })).toHaveCount(0);
});
