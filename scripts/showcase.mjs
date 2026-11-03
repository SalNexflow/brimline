#!/usr/bin/env node
// README screenshots and the demo video (M11).
//
//   node scripts/showcase.mjs screenshots          -> docs/screenshots/*.png
//   node scripts/showcase.mjs video                -> docs/video/brimline-demo.mp4 (replayed AI)
//   node scripts/showcase.mjs <what> --record-missing -> records only replies not yet in the
//                                                     recording (live model for new prompts only)
//   node scripts/showcase.mjs video --record       -> records the model replies first (live
//                                                     model, DEEPSEEK_API_KEY; a few cents)
//
// Both run the app on its own ports and database (apps/web/demo/playwright.config.ts) with fake
// seeded data moved to this week and a plan already approved.
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(ROOT, "apps", "web");
const RECORDING = join(ROOT, "eval", "recordings", "demo.jsonl");
const META = join(ROOT, "eval", "recordings", "demo.meta.json");
const OUT_DIR = join(WEB, "test-results", "showcase");

const what = process.argv[2];
const record = process.argv.includes("--record");
const recordMissing = process.argv.includes("--record-missing");
if (what !== "screenshots" && what !== "video" && what !== "stills") {
  console.error("Usage: node scripts/showcase.mjs <screenshots|video|stills> [--record | --record-missing]");
  process.exit(2);
}

function run(command, env = {}) {
  console.log(`\n▶ ${command}`);
  const { status } = spawnSync(command, { cwd: WEB, shell: true, stdio: "inherit", env: { ...process.env, ...env } });
  if (status !== 0) process.exit(status ?? 1);
}

run("pnpm run build");
if (record) rmSync(RECORDING, { force: true }); // a recording is one run, start to end
rmSync(OUT_DIR, { recursive: true, force: true });
mkdirSync(join(ROOT, "docs", "screenshots"), { recursive: true });
run("pnpm exec playwright test -c demo/playwright.config.ts", {
  SHOWCASE: what,
  SHOWCASE_AI_MODE: record || recordMissing ? "record" : "replay",
  // Screenshots only: the same walkthrough at high speed, without video.
  ...(what === "screenshots" ? { SHOWCASE_PACE: "0.05" } : {}),
});
if (record || recordMissing) {
  writeFileSync(META, JSON.stringify({ recorded_at: new Date().toISOString(), model: "deepseek-flash" }, null, 2) + "\n");
  console.log(`Recorded replies in ${RECORDING}`);
}

if (what === "video") {
  // Playwright records WebM; ffmpeg (from the ffmpeg-static dev dependency) writes an MP4.
  const webm = findFile(OUT_DIR, ".webm");
  if (!webm) {
    console.error("✗ no video was recorded");
    process.exit(1);
  }
  const ffmpeg = createRequire(join(WEB, "package.json"))("ffmpeg-static");
  const out = join(ROOT, "docs", "video", "brimline-demo.mp4");
  mkdirSync(dirname(out), { recursive: true });
  const { status } = spawnSync(
    ffmpeg,
    ["-y", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-movflags", "+faststart", out],
    { stdio: "inherit" },
  );
  if (status !== 0) process.exit(status ?? 1);
  console.log(`\n✓ ${out} (${(statSync(out).size / 1_048_576).toFixed(1)} MB)`);
}

function findFile(dir, ext) {
  if (!existsSync(dir)) return null;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      const found = findFile(p, ext);
      if (found) return found;
    } else if (name.endsWith(ext)) return p;
  }
  return null;
}
