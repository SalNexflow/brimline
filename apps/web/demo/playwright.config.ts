import { existsSync } from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// The README screenshots and the demo video (M11): `make screenshots`, `make demo-video`.
// Their own ports and database, so they never touch development or the gate. The engine runs in
// demo mode on the seed moved to this week, with a plan already approved, and model replies
// replayed from a recorded run (AI_MODE=replay; `make demo-video -- --record` records them once).
const WEB_PORT = 3200;
const ENGINE_PORT = 8200;
const DATABASE = "brimline_showcase";

const repoRoot = path.resolve(__dirname, "..", "..", "..");
const envFile = path.join(repoRoot, ".env");
if (existsSync(envFile)) process.loadEnvFile(envFile);

function withDatabase(url: string | undefined, name: string): string {
  if (!url) throw new Error("DATABASE_URL is not set (run `make setup`)");
  const parsed = new URL(url);
  parsed.pathname = `/${name}`;
  return parsed.toString();
}

const video = process.env.SHOWCASE === "video";

export default defineConfig({
  testDir: ".",
  testMatch: "video.spec.ts", // screenshots are taken during the walkthrough
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 10 * 60_000,
  reporter: "list",
  outputDir: path.join(repoRoot, "apps", "web", "test-results", "showcase"),
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    actionTimeout: 30_000, // a missing element fails in seconds, not at the run's 10-minute limit
    viewport: { width: 1280, height: 720 },
    colorScheme: "light",
    video: video ? { mode: "on", size: { width: 1280, height: 720 } } : "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 } } }],
  webServer: [
    {
      command: `uv run --locked python -m brimline_engine.db reset --demo --database ${DATABASE} && uv run --locked uvicorn brimline_engine.main:app --port ${ENGINE_PORT}`,
      cwd: path.join(repoRoot, "services", "engine"),
      url: `http://localhost:${ENGINE_PORT}/health`,
      env: {
        DATABASE_URL: withDatabase(process.env.DATABASE_URL, DATABASE),
        DEMO_LOGIN: "true",
        DEMO_MODE: "true",
        AI_MODE: process.env.SHOWCASE_AI_MODE ?? "replay",
        DEMO_CLOCK: "Mon 10:00", // the shop clock pinned inside a shift, as on the hosted demo (M12)
        SIM_FREE_PORTS: "true", // the simulated machines on ports the system picks
      },
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      command: `pnpm exec next start --port ${WEB_PORT}`,
      cwd: path.join(repoRoot, "apps", "web"),
      url: `http://localhost:${WEB_PORT}`,
      env: { ENGINE_URL: `http://localhost:${ENGINE_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
