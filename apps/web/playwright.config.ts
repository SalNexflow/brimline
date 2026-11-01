import { existsSync } from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Separate ports from `make dev` (3000 and 8000), so the gate never tests a stale dev server and
// never touches your development database.
const WEB_PORT = 3100;
const ENGINE_PORT = 8100;
const E2E_DATABASE = "brimline_e2e";

const repoRoot = path.resolve(__dirname, "..", "..");
const envFile = path.join(repoRoot, ".env");
if (existsSync(envFile)) process.loadEnvFile(envFile);

function withDatabase(url: string | undefined, name: string): string {
  if (!url) throw new Error("DATABASE_URL is not set (run `make setup`)");
  const parsed = new URL(url);
  parsed.pathname = `/${name}`;
  return parsed.toString();
}

export default defineConfig({
  testDir: "./e2e",
  // Tests share one database and create orders, so they run one at a time.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  // In CI, also write the HTML report that the workflow uploads when a test fails.
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // A freshly reset and seeded database for every run, then the engine on top of it.
      command: `uv run --locked python -m brimline_engine.db reset --database ${E2E_DATABASE} && uv run --locked uvicorn brimline_engine.main:app --port ${ENGINE_PORT}`,
      cwd: path.join(repoRoot, "services", "engine"),
      url: `http://localhost:${ENGINE_PORT}/health`,
      env: {
        DATABASE_URL: withDatabase(process.env.DATABASE_URL, E2E_DATABASE),
        DEMO_LOGIN: "true",
        AI_MODE: "fake", // prepared replies: browser tests never call a real model
        SIM_MACHINES: "true", // the six simulated machines (M12), on ports the system picks
        SIM_FREE_PORTS: "true",
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // The gate runs `next build` first; tests run against that production build.
      command: `pnpm exec next start --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      env: { ENGINE_URL: `http://localhost:${ENGINE_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
