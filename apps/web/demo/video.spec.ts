import { readFileSync } from "node:fs";
import path from "node:path";

import { mkdirSync, writeFileSync } from "node:fs";

import { expect, test, type Locator, type Page } from "@playwright/test";

// The demo video (M11): `make demo-video`. One run through the story, recorded by Playwright and
// turned into an MP4 (docs/video/brimline-demo.mp4). Fake seeded data; model replies are
// replayed from a recorded run (eval/recordings/demo.jsonl), which the opening card says.
// About three minutes: each caption stays up long enough to read.

// SHOWCASE=stills runs the same story without cards or captions and saves 1920 x 1080 stills of the
// app for the product video (video/public/stills/); the README screenshots are left alone.
const STILLS = process.env.SHOWCASE === "stills";

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
  if (STILLS) return;
  await page.setContent(`<!doctype html><html><body style="margin:0;height:100vh;display:grid;place-items:center;
    background:#0e6a6a;color:#fff;font-family:'Segoe UI',system-ui,sans-serif;text-align:center">
    <div style="max-width:960px;padding:0 48px">
      <h1 style="font-size:46px;margin:0 0 24px">${title}</h1>
      ${lines.map((l) => `<p style="font-size:24px;line-height:1.45;margin:10px 0">${l}</p>`).join("")}
    </div></body></html>`);
  await page.waitForTimeout(seconds * READ);
}

async function say(page: Page, text: string, seconds = 4) {
  if (STILLS) return;
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
  if (STILLS) return;
  if (top) {
    // Put this heading at the top of the picture.
    await page.getByRole("heading", { name: top, exact: true }).first().evaluate((el) => el.scrollIntoView({ block: "start" }));
  }
  // Off the icon rail, which opens on hover and would cover the page; then let every animation
  // and transition finish (motion is on in the showcase).
  await page.mouse.move(1200, 700);
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

// Stills for the product video: the page with a heading at the top, or an element in the middle.
const STILL_DIR = path.resolve(__dirname, "..", "..", "..", "video", "public", "stills");

// Where the camera's targets are in each still (CSS pixels of the 1920 x 1080 viewport), measured
// here rather than by eye, written to stills/boxes.json for the video.
const boxes: Record<string, Record<string, { x: number; y: number; w: number; h: number }>> = {};

async function still(page: Page, name: string, place?: { top?: string; center?: Locator; marks?: Record<string, Locator> }) {
  if (!STILLS) return;
  mkdirSync(STILL_DIR, { recursive: true });
  // Streamed sections show "Loading …" first: wait until every one has arrived.
  await expect(page.getByText(/^(Loading|Asking|Checking|Searching)\b.*…$/)).toHaveCount(0, { timeout: 30_000 });
  if (place?.top) {
    await page.getByRole("heading", { name: place.top, exact: true }).first().evaluate((el) => el.scrollIntoView({ block: "start" }));
  }
  if (place?.center) await place.center.evaluate((el) => el.scrollIntoView({ block: "center" }));
  await page.mouse.move(1900, 1060); // off the icon rail, which opens on hover
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
  await page.screenshot({ path: path.join(STILL_DIR, `${name}.png`) });
  boxes[name] = {};
  for (const [key, target] of Object.entries(place?.marks ?? {})) {
    const b = await target.boundingBox();
    if (!b) throw new Error(`still ${name}: ${key} is not on screen`);
    boxes[name][key] = { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
  }
  writeFileSync(path.join(STILL_DIR, "boxes.json"), JSON.stringify(boxes, null, 2) + "\n");
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
      "All data in this video is fake. The machines are simulated: mock servers that speak each machine's protocol.",
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
  await expect(page.getByRole("heading", { name: "Customer message" })).toBeVisible();
  await still(page, "quote-draft", {
    marks: { message: page.locator("blockquote").first(), lines: page.getByRole("region", { name: /^Lines/ }) },
  });
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
  await still(page, "quote-price", {
    center: page.getByTestId("quote-total"),
    marks: { total: page.getByTestId("quote-total"), byRules: page.getByText(/not by AI\.$/) },
  });
  await page.getByTestId("quote-total").scrollIntoViewIfNeeded();
  await say(page, "Grams and print minutes came from the file; the price comes from the shop's rules, never from AI.", 6);
  await page.getByRole("button", { name: "Approve and create order" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("approved");
  await say(page, "Approving creates the order, with the part size the file gave. Audit-logged.", 4);

  // 3. The planner plans the day.
  await card(page, "3 · Plan", ["A constraint solver plans; an independent checker re-checks every plan."], 3);
  await signIn(page, "Priya Nandakumar", "planner");
  await still(page, "orders");
  await page.getByRole("link", { name: "Board" }).click();
  await expect(page.getByRole("heading", { name: "Approved plan", exact: true })).toBeVisible();
  await shot(page, "board", "Approved plan");
  await still(page, "board-check", {
    top: "Approved plan",
    marks: { badge: page.getByTestId("check-badge").first(), stats: page.locator(".stats").first() },
  });
  await say(page, "The board starts with an approved plan. The new order is not in it yet.", 4);
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toBeVisible({ timeout: 180_000 });
  await page.getByTestId("check-badge").first().scrollIntoViewIfNeeded();
  await say(page, "Plan day: the draft includes the new order, and the independent checker passed it.", 5);
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);
  await say(page, "Nothing reaches an operator's queue until a planner approves.", 3);

  // 4. Materials (M9).
  await card(page, "4 · Materials", ["Stock and deliveries limit the plan. Code says what runs short and what to order."], 3);
  await page.goto("/materials");
  const shortage = page.getByTestId("shortage-TPU-BLACK").first();
  await expect(shortage).toBeVisible();
  await shortage.scrollIntoViewIfNeeded();
  await still(page, "materials-short", { center: shortage });
  await say(page, "TPU-BLACK runs short before its delivery. The clip waits; nothing starts without its material.", 5);
  await say(page, "A suggestion: what to order, how much, and by when. Code computes it; a person orders.", 5);

  // 5. Dispatch to a machine (M12).
  await card(page, "5 · Dispatch", ["An AI agent proposes; a person presses Proceed; code checks every call."], 3);
  await signIn(page, "Jonas Weber", "operator");
  await page.goto("/queues");
  await expect(page.getByRole("button", { name: /^Start: Prep for BL-0005 Chain guide/ })).toBeVisible();
  await still(page, "queues");
  await page.getByRole("button", { name: /^Start: Prep for BL-0005 Chain guide/ }).click();
  await page.getByRole("button", { name: /^Done: Prep for BL-0005 Chain guide/ }).click();
  await say(page, "The operator finishes the chain guide's prep, so its milling can start.", 3);
  await signIn(page, "Priya Nandakumar", "planner");
  await page.goto("/dispatch");
  await expect(page.getByTestId("machine-CNC-1")).toContainText("Idle");
  await say(page, "Six simulated machines, each reached through its own protocol. Demo time is pinned inside a shift.", 5);
  await page.getByRole("button", { name: "Ask the dispatcher" }).click();
  const proposal = page.getByRole("checkbox", { name: /Start BL-0005-1 on CNC-1/ });
  await expect(proposal).toBeVisible();
  await proposal.scrollIntoViewIfNeeded();
  await say(page, "The agent proposes; the guard pre-checks it. Nothing has reached a machine.", 4);
  await proposal.check();
  await still(page, "dispatch-proposal", {
    center: proposal,
    marks: { proposals: page.locator(".proposals"), proceed: page.getByRole("button", { name: "Proceed" }) },
  });
  await page.getByRole("button", { name: "Proceed" }).click();
  await expect(page.getByTestId("call-row").filter({ hasText: "start_task" })).toContainText("allowed");
  await page.getByTestId("call-row").first().scrollIntoViewIfNeeded();
  await still(page, "dispatch-log", {
    center: page.getByTestId("call-row").first(),
    marks: { row: page.getByTestId("call-row").filter({ hasText: "start_task" }).first() },
  });
  await say(page, "After Proceed the agent issues exactly that call; code checked it against the plan, the machine and the stock.", 6);
  await page.getByTestId("machine-CNC-1").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("machine-CNC-1")).toContainText("Running");
  await still(page, "dispatch-machine", {
    center: page.getByTestId("machine-CNC-1"),
    marks: { machine: page.getByTestId("machine-CNC-1") },
  });
  await say(page, "The simulated mill (GRBL) is running the job.", 3);

  // 6. Something breaks.
  await card(page, "6 · Disruption", ["The planner types what broke. AI reads it; code resolves the times."], 3);
  await page.goto("/board"); // the title card replaced the page
  await page.getByLabel("What happened?").fill("Printer 1 jammed for 4 hours");
  await still(page, "disruption-entry", {
    center: page.getByLabel("What happened?"),
    marks: { box: page.getByLabel("What happened?") },
  });
  await page.getByRole("button", { name: "Read message" }).click();
  const review = page.getByRole("article").filter({ hasText: "Printer 1 jammed for 4 hours" });
  await expect(review.getByRole("heading", { name: "Check how this was understood" })).toBeVisible();
  await review.scrollIntoViewIfNeeded();
  await shot(page, "disruption-review", "Check how this was understood");
  await still(page, "disruption-review", { top: "Check how this was understood" });
  await say(page, "Read as: FDM-1 down for 4 hours from when it was reported, with the time worked out by code. The planner checks it first.", 5);
  await review.getByRole("button", { name: "Confirm these events" }).click();
  await page.getByRole("button", { name: "Plan day" }).click();
  await expect(page.getByRole("heading", { name: "What changes against the approved plan" })).toBeVisible({ timeout: 180_000 });
  await page.getByRole("heading", { name: "What changes against the approved plan" }).scrollIntoViewIfNeeded();
  await still(page, "replan-diff", {
    top: "What changes against the approved plan",
    marks: { moves: page.getByRole("heading", { name: "What changes against the approved plan" }) },
  });
  await still(page, "replan-approve", {
    center: page.getByRole("button", { name: "Approve plan" }),
    marks: { approve: page.getByRole("button", { name: "Approve plan" }) },
  });
  await say(page, "The re-plan moves as few jobs as it can, shows exactly what changes, and is checked again.", 6);
  await page.getByRole("button", { name: "Approve plan" }).click();
  await expect(page.getByRole("heading", { name: "Draft plan, waiting for approval" })).toHaveCount(0);

  // 5. Search.
  await card(page, "7 · Search", ["A question becomes a typed filter. Permissions are added by code."], 3);
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
