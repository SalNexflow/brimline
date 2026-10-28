import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// The demo video (M11): `make demo-video`. One run through the story, recorded by Playwright and
// turned into an MP4 (docs/video/brimline-demo.mp4). Fake seeded data; model replies are
// replayed from a recorded run (eval/recordings/demo.jsonl), which the opening card says.
// About three minutes: each caption stays up long enough to read.

// Seconds on screen are multiplied by this pace (1.9 gives about three minutes in all).
const PACE = Number(process.env.SHOWCASE_PACE ?? "1.9");
const READ = PACE * 1000; // milliseconds per caption second

function recordedOn(): string {
  // The date the replies were recorded, from the recording itself (never typed by hand).
  const file = path.resolve(__dirname, "..", "..", "..", "eval", "recordings", "demo.meta.json");
  try {
    return (JSON.parse(readFileSync(file, "utf8")) as { recorded_at: string }).recorded_at.slice(0, 10);
  } catch {
    return "an earlier run";
  }
}

async function card(page: Page, title: string, lines: string[], seconds: number) {
  await page.setContent(`<!doctype html><html><body style="margin:0;height:100vh;display:grid;place-items:center;
    background:#0e6a6a;color:#fff;font-family:'Segoe UI',system-ui,sans-serif;text-align:center">
    <div style="max-width:960px;padding:0 48px">
      <h1 style="font-size:46px;margin:0 0 24px">${title}</h1>
      ${lines.map((l) => `<p style="font-size:24px;line-height:1.45;margin:10px 0">${l}</p>`).join("")}
    </div></body></html>`);
  await page.waitForTimeout(seconds * READ);
}

async function say(page: Page, text: string, seconds = 4) {
  await page.evaluate((t) => {
    let el = document.getElementById("demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-caption";
      el.setAttribute(
        "style",
        "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:1100px;z-index:99999;" +
          "background:rgba(14,26,28,.92);color:#fff;padding:14px 22px;border-radius:10px;" +
          "font:500 20px/1.4 'Segoe UI',system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25)",
      );
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
  await page.waitForTimeout(seconds * READ);
}

// The README screenshots are taken during the same run (`make screenshots` runs it fast, without
// video), so their model replies are exactly the recorded ones.
const SHOTS = path.resolve(__dirname, "..", "..", "..", "docs", "screenshots");

async function shot(page: Page, name: string, top?: string) {
  if (top) {
    // Put this heading at the top of the picture.
    await page.getByRole("heading", { name: top, exact: true }).first().evaluate((el) => el.scrollIntoView({ block: "start" }));
  }
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

async function signIn(page: Page, name: string, role: string) {
  await page.goto("/login");
  await page.getByRole("button", { name: `Sign in as ${name}, ${role}` }).click();
  await expect(page).toHaveURL(/\/orders$/);
}

/** A 60 x 40 x 20 mm closed block as binary STL: a stand-in for the customer's model. */
function blockStl(): Buffer {
  const [x, y, z] = [60, 40, 20];
  const v = (a: number, b: number, c: number) => [a * x, b * y, c * z];
  const quads = [
    [v(0, 0, 0), v(0, 1, 0), v(1, 1, 0), v(1, 0, 0)],
    [v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)],
    [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)],
    [v(0, 1, 0), v(0, 1, 1), v(1, 1, 1), v(1, 1, 0)],
    [v(0, 0, 0), v(0, 0, 1), v(0, 1, 1), v(0, 1, 0)],
    [v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)],
  ];
  const tris = quads.flatMap(([a, b, c, d]) => [
    [a, b, c],
    [a, c, d],
  ]);
  const out = Buffer.alloc(84 + 50 * tris.length);
  out.writeUInt32LE(tris.length, 80);
  tris.forEach((t, i) => t.flat().forEach((n, j) => out.writeFloatLE(n!, 84 + 50 * i + 12 + 4 * j)));
  return out;
}

test("the Brimline story, end to end", async ({ page }) => {
  await card(
    page,
    "Brimline",
    [
      "Planning software for a fictional made-to-order 3D-print and CNC shop.",
      "All data in this video is fake.",
      `AI replies are replayed from a recorded run (deepseek-flash, ${recordedOn()}).`,
      "Prices, dates, permissions and plans are always computed by code.",
    ],
    8,
  );

  // 1. A customer's message and model file.
  await card(page, "1 · A customer asks", ["A message and a 3D model file."], 3);
  await signIn(page, "Mia Chen", "customer");
  await page.goto("/quotes/new");
  await page.getByRole("textbox", { name: "Message" }).fill("Hi! 20 phone stands, black PETG, need by Friday. Thanks, Mia");
  await say(page, "Mia, a customer, types her request in her own words.", 3);
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page).toHaveURL(/\/quotes\/Q-\d{4}$/);
  const quoteUrl = page.url();
  await say(page, "AI reads it into a draft; code works out the due date and lists what is still missing.", 5);
  await page.getByRole("link", { name: "Upload a model file" }).click();
  await page.getByLabel(/Model file \(STL or 3MF/).setInputFiles({ name: "phone-stand.stl", mimeType: "model/stl", buffer: blockStl() });
  await page.getByRole("button", { name: "Upload and check" }).click();
  await expect(page).toHaveURL(/\/files\/F-\d{4}$/);
  await say(page, "Code measures the file: closed surface, size, fit per printer, walls, overhangs, loose parts.", 6);

  // 2. The shop prices and approves it.
  await card(page, "2 · Quote", ["Code prices it from the file's measurements; a person approves."], 3);
  await signIn(page, "Sam Ortega", "staff");
  await page.goto(quoteUrl);
  await expect(page.getByTestId("quote-total")).toBeVisible();
  await shot(page, "quote", "Model files");
  await page.getByTestId("quote-total").scrollIntoViewIfNeeded();
  await say(page, "Grams and print minutes came from the file; the price comes from the shop's rules, never from AI.", 6);
  await page.getByRole("button", { name: "Approve and create order" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("approved");
  await say(page, "Approving creates the order, with the part size the file gave. Audit-logged.", 4);

  // 3. The planner plans the day.
  await card(page, "3 · Plan", ["A constraint solver plans; an independent checker re-checks every plan."], 3);
  await signIn(page, "Priya Nandakumar", "planner");
  await page.getByRole("link", { name: "Board" }).click();
  await expect(page.getByRole("heading", { name: "Approved plan", exact: true })).toBeVisible();
  await shot(page, "board", "Approved plan");
  await say(page, "The board starts with an approved plan. The new order is not in it yet.", 4);
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toBeVisible({ timeout: 180_000 });
  await page.getByTestId("check-badge").first().scrollIntoViewIfNeeded();
  await say(page, "Plan day: the draft includes the new order, and the independent checker passed it.", 5);
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);
  await say(page, "Nothing reaches an operator's queue until a planner approves.", 3);

  // 4. Something breaks.
  await card(page, "4 · Disruption", ["The planner types what broke. AI reads it; code resolves the times."], 3);
  await page.goto("/board"); // the title card replaced the page
  await page.getByLabel("What happened?").fill("printer 3 jammed until 5pm");
  await page.getByRole("button", { name: "Read message" }).click();
  const review = page.getByRole("article").filter({ hasText: "printer 3 jammed until 5pm" });
  await expect(review.getByRole("heading", { name: "Check how this was understood" })).toBeVisible();
  await review.scrollIntoViewIfNeeded();
  await shot(page, "disruption-review", "Check how this was understood");
  await say(page, "Read as: FDM-3 down until 5 pm, with the time worked out by code. The planner checks it first.", 5);
  await review.getByRole("button", { name: "Confirm these events" }).click();
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("heading", { name: "What changes against the approved plan" })).toBeVisible({ timeout: 180_000 });
  await page.getByRole("heading", { name: "What changes against the approved plan" }).scrollIntoViewIfNeeded();
  await say(page, "The re-plan moves as few jobs as it can, shows exactly what changes, and is checked again.", 6);
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);

  // 5. Search.
  await card(page, "5 · Search", ["A question becomes a typed filter. Permissions are added by code."], 3);
  await page.goto("/search");
  await page.getByRole("textbox", { name: "Question" }).fill("jobs due this week not printed yet");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByTestId("search-description")).toBeVisible();
  await shot(page, "search", "Filter");
  await say(page, "AI returned a filter, never SQL. The chips show exactly what was searched.", 5);
  await page.getByRole("button", { name: "Remove Printed" }).click();
  await expect(page.getByText("Printed: no")).toHaveCount(0);
  await say(page, "Editing a chip runs the search again with no AI call at all.", 4);

  await card(
    page,
    "Try it yourself",
    ["git clone · make setup · make gate · make demo", "Every number in the README comes from a command."],
    6,
  );
});
