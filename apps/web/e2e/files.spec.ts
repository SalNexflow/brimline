import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// M7: a model file, measured by code, fills a quote line's part size, grams and minutes; a
// file that fails its checks blocks approval. The test makes its own models (a 40 mm cube, and
// a 401 mm cube that fits no printer), so there is no copyright question.
// By hand: PETG 64 cm³ x 1.27 g/cm³ x 0.5 fill = 41 g; 32,000 mm³ / 300 mm³ per min = 107 min.
// Price: 20 x 41 g x 4 c + 20 x 107 min x 6 c + 1500 setup = 3280 + 12840 + 1500 = €176.20.

const STAFF = { name: "Sam Ortega", role: "staff" };

/** A closed box as binary STL, faces wound outwards. */
function boxStl(size: number): Buffer {
  const s = size;
  const v = (x: number, y: number, z: number) => [x * s, y * s, z * s];
  const quads = [
    [v(0, 0, 0), v(0, 1, 0), v(1, 1, 0), v(1, 0, 0)], // bottom (z = 0), facing down
    [v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)], // top
    [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)], // front (y = 0)
    [v(0, 1, 0), v(0, 1, 1), v(1, 1, 1), v(1, 1, 0)], // back
    [v(0, 0, 0), v(0, 0, 1), v(0, 1, 1), v(0, 1, 0)], // left (x = 0)
    [v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)], // right
  ];
  const triangles = quads.flatMap(([a, b, c, d]) => [
    [a, b, c],
    [a, c, d],
  ]);
  const kept = triangles;
  const out = Buffer.alloc(84 + 50 * kept.length);
  out.writeUInt32LE(kept.length, 80);
  kept.forEach((tri, i) => {
    const base = 84 + 50 * i + 12; // normals left zero
    tri.flat().forEach((n, j) => out.writeFloatLE(n!, base + 4 * j));
  });
  return out;
}

async function signIn(page: Page, user: { name: string; role: string }) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${user.name}, ${user.role}` }).click();
  await expect(page).toHaveURL(/\/orders$/);
}

async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const problems = results.violations.map(
    (v) => `${v.id}: ${v.help} at ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`,
  );
  expect(problems).toEqual([]);
}

async function uploadFor(page: Page, linkName: string, name: string, buffer: Buffer) {
  await page.getByRole("link", { name: linkName }).click();
  await expect(page.getByRole("heading", { name: "Upload a model file" })).toBeVisible();
  await page.getByLabel("Model file (STL or 3MF, up to 25 MiB)").setInputFiles({ name, mimeType: "model/stl", buffer });
  await page.getByRole("button", { name: "Upload and check" }).click();
  await expect(page).toHaveURL(/\/files\/F-\d{4}$/);
}

test("a checked model file fills the quote line; a broken file blocks approval", async ({ page }) => {
  await signIn(page, STAFF);
  await page.goto("/quotes/new");
  await page.getByRole("combobox", { name: "Customer", exact: true }).selectOption({ label: "Harbor Lane Robotics Club" });
  await page.getByRole("textbox", { name: "Message" }).fill("20 phone stands, black PETG, need by Friday.");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page).toHaveURL(/\/quotes\/Q-\d{4}$/);
  const quoteUrl = page.url();

  await uploadFor(page, "Upload a model file", "stand.stl", boxStl(40));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^File F-\d{4} Pass$/);
  await expect(page.getByTestId("file-part-size")).toHaveText("40 x 40 x 40 mm (rounded up)");
  await expect(page.getByRole("heading", { name: "Advice (AI, not a check)" })).toBeVisible();
  const preview = page.getByRole("img", { name: "Top, front and side views of stand.stl" });
  await expect(preview).toBeVisible();
  expect(await preview.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(680);
  await expectAccessible(page);

  await page.getByRole("link", { name: /Back to quote/ }).click();
  await expect(page).toHaveURL(quoteUrl);
  const form = page.getByRole("form", { name: "Edit quote" });
  await expect(form.getByRole("spinbutton", { name: "Line 1 part size x" })).toHaveValue("40");
  await expect(form.getByRole("spinbutton", { name: "Line 1 grams per part" })).toHaveValue("41");
  await expect(form.getByRole("spinbutton", { name: "Line 1 minutes per part" })).toHaveValue("107");
  // Due date and everything else were known: code prices the line from the file's numbers.
  await expect(page.getByTestId("quote-total")).toHaveText("€176.20");

  await uploadFor(page, "Upload a new version", "stand-v2.stl", boxStl(401));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^File F-\d{4} Fail$/);
  await expect(page.getByRole("cell", { name: /fits no fdm machine/ })).toBeVisible();
  await page.goto(quoteUrl);
  await page.getByRole("button", { name: "Approve and create order" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Please fix" })).toContainText("failed its checks");
});
