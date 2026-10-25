#!/usr/bin/env node
// The single task runner. `make <task>` and `pnpm run <task>` both call this file, so every task
// behaves the same in PowerShell, Git Bash, and CI (GNU make on Windows picks a different shell
// depending on where it is started; Node does not). See docs/DECISIONS.md D3.
//
// Usage: node scripts/tasks.mjs <setup|dev|gate|test|eval|bench|gate-selftest>

import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(ROOT, "apps", "web");
const ENGINE = join(ROOT, "services", "engine");
const IS_CI = !!process.env.CI;

// Next.js sends anonymous telemetry by default; a quality gate should not phone home.
const ENV = { ...process.env, NEXT_TELEMETRY_DISABLED: "1" };

// A step is one command in one folder. `shell: true` because pnpm and uv are .cmd shims on
// Windows; the folder goes in `cwd` (never in the command string) so spaces in paths are safe.
const step = (name, cwd, command) => ({ name, cwd, command });

const WEB_UNIT = step("web: unit tests", WEB, "pnpm run test");
const ENGINE_UNIT = step("engine: tests", ENGINE, "uv run --locked pytest");

// Order: fastest checks first, so most mistakes fail in seconds.
const GATE = [
  step("web: typecheck", WEB, "pnpm run typecheck"),
  step("web: lint", WEB, "pnpm run lint"),
  WEB_UNIT,
  step("engine: lint", ENGINE, "uv run --locked ruff check"),
  step("engine: format", ENGINE, "uv run --locked ruff format --check"),
  step("engine: typecheck", ENGINE, "uv run --locked mypy"),
  ENGINE_UNIT,
  step("web: build", WEB, "pnpm run build"),
  step("web: browser tests", WEB, "pnpm run e2e"),
];

function runSteps(title, steps) {
  const results = [];
  for (const s of steps) {
    console.log(`\n▶ ${s.name}  (${s.command})`);
    const started = Date.now();
    const { status } = spawnSync(s.command, { cwd: s.cwd, env: ENV, shell: true, stdio: "inherit" });
    const ok = status === 0;
    results.push({ name: s.name, ok, seconds: (Date.now() - started) / 1000 });
    if (!ok) break; // stop at the first failure: later steps would only add noise
  }

  console.log(`\n${title}`);
  for (const r of results) console.log(`  ${r.ok ? "PASS" : "FAIL"}  ${r.name}  (${r.seconds.toFixed(1)}s)`);
  const failed = results.find((r) => !r.ok);
  console.log(failed ? `\n✗ ${title} FAILED at: ${failed.name}` : `\n✓ ${title} green`);

  // The gate self-test reads this file to check *which* step caught each planted error.
  if (process.env.GATE_RESULT_FILE) {
    writeFileSync(process.env.GATE_RESULT_FILE, JSON.stringify({ failedStep: failed?.name ?? null }));
  }
  return failed ? 1 : 0;
}

function requireTool(command, hint) {
  const { status } = spawnSync(`${command} --version`, { shell: true, stdio: "ignore" });
  if (status !== 0) {
    console.error(`✗ '${command}' not found. ${hint}`);
    process.exit(1);
  }
}

function setup() {
  const [major] = process.versions.node.split(".").map(Number);
  if (major < 24) {
    console.error(`✗ Node ${process.versions.node} found; Brimline needs Node 24 or newer.`);
    return 1;
  }
  requireTool("pnpm", "Install with: npm install -g pnpm");
  requireTool("uv", "Install from https://docs.astral.sh/uv/ (Windows: winget install astral-sh.uv)");
  requireTool("docker", "Install Docker Desktop and start it.");

  if (!existsSync(join(ROOT, ".env"))) {
    copyFileSync(join(ROOT, ".env.example"), join(ROOT, ".env"));
    console.log("Created .env from .env.example");
  }

  // Linux CI runners also need the browser's system libraries.
  const browser = IS_CI && process.platform === "linux" ? "chromium --with-deps" : "chromium";
  return runSteps("setup", [
    step("install web dependencies", ROOT, "pnpm install --frozen-lockfile"),
    step("install engine dependencies", ENGINE, "uv sync --locked"),
    step("install browser for tests", WEB, `pnpm exec playwright install ${browser}`),
    step("start database (waits for health check)", ROOT, "docker compose up -d --wait"),
  ]);
}

function dev() {
  const db = spawnSync("docker compose up -d --wait", { cwd: ROOT, env: ENV, shell: true, stdio: "inherit" });
  if (db.status !== 0) return 1;

  const services = [
    { label: "engine", cwd: ENGINE, command: "uv run uvicorn brimline_engine.main:app --reload --port 8000" },
    { label: "web   ", cwd: WEB, command: "pnpm run dev" },
  ];
  const children = services.map(({ label, cwd, command }) => {
    const child = spawn(command, { cwd, env: ENV, shell: true });
    const prefix = (chunk) =>
      chunk.toString().split(/\r?\n/).filter(Boolean).forEach((line) => console.log(`[${label}] ${line}`));
    child.stdout.on("data", prefix);
    child.stderr.on("data", prefix);
    return child;
  });

  // With shell: true the real server is a grandchild, so kill the whole process tree.
  const stopAll = () => {
    for (const child of children) {
      if (process.platform === "win32") spawnSync(`taskkill /pid ${child.pid} /T /F`, { shell: true, stdio: "ignore" });
      else child.kill("SIGTERM");
    }
    process.exit(0);
  };
  process.on("SIGINT", stopAll);
  process.on("SIGTERM", stopAll);
  console.log("web: http://localhost:3000   engine: http://localhost:8000/health   (Ctrl+C stops both)");
  return null; // keep running
}

function notYet(task, milestone) {
  // An honest stub: says what is missing instead of printing made-up numbers (hard rule 11).
  console.log(`'${task}' has nothing to run yet. It arrives in ${milestone} (see docs/MILESTONES.md).`);
  return 0;
}

const TASKS = {
  setup,
  dev,
  gate: () => runSteps("gate", GATE),
  test: () => runSteps("unit tests", [WEB_UNIT, ENGINE_UNIT]),
  eval: () => notYet("eval", "M2"),
  bench: () => notYet("bench", "M3"),
  "gate-selftest": () =>
    spawnSync(`node "${join(ROOT, "scripts", "gate_selftest.mjs")}"`, { cwd: ROOT, env: ENV, shell: true, stdio: "inherit" })
      .status ?? 1,
};

const task = process.argv[2];
if (!task || !(task in TASKS)) {
  console.error(`Usage: node scripts/tasks.mjs <${Object.keys(TASKS).join("|")}>`);
  process.exit(2);
}
const code = TASKS[task]();
if (code !== null) process.exit(code);
