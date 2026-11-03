// Render a composition: node scripts/render.mjs [CompositionId] -> out/<id>.mp4
// 1. Reads every number from the result files (numbers.mjs; fails if one is missing).
// 2. Makes the sound effects (sfx.mjs, from formulas with the repo's ffmpeg).
// 3. Checks the app stills exist (made by SHOWCASE=stills on the showcase stack).
// 4. Renders with the Chromium that Playwright already installed, so Remotion downloads no browser.
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const id = process.argv[2] ?? "TestChecker";

function run(cmd, args) {
  const r = spawnSync(cmd, args, { cwd: ROOT, stdio: "inherit", shell: process.platform === "win32" });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

run("node", ["scripts/numbers.mjs"]);
run("node", ["scripts/sfx.mjs"]);

const stills = join(ROOT, "public", "stills");
if (!existsSync(join(stills, "board-check.png"))) {
  console.error("✗ missing app stills: run `SHOWCASE=stills pnpm exec playwright test -c demo/playwright.config.ts` in apps/web");
  process.exit(1);
}

// Playwright's headless Chromium (newest installed build).
const pw = process.env.PLAYWRIGHT_BROWSERS_PATH ?? join(process.env.LOCALAPPDATA ?? join(homedir(), ".cache"), "ms-playwright");
const shells = existsSync(pw) ? readdirSync(pw).filter((d) => d.startsWith("chromium_headless_shell-")).sort() : [];
const exe = shells
  .reverse()
  .flatMap((d) => ["chrome-headless-shell-win64/chrome-headless-shell.exe", "chrome-win/headless_shell.exe", "chrome-linux/headless_shell"].map((p) => join(pw, d, p)))
  .find(existsSync);
if (!exe) {
  console.error("✗ no Playwright Chromium found: run `pnpm exec playwright install chromium` in apps/web");
  process.exit(1);
}

run("pnpm", ["exec", "remotion", "render", "src/index.ts", id, `out/${id}.mp4`, `--browser-executable=${exe}`, "--crf=18"]);
