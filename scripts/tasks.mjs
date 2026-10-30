#!/usr/bin/env node
// The single task runner. `make <task>` and `pnpm run <task>` both call this file, so every task
// behaves the same in PowerShell, Git Bash, and CI (GNU make on Windows picks a different shell
// depending on where it is started; Node does not). See docs/DECISIONS.md D3.
//
// Usage: node scripts/tasks.mjs <setup|dev|gate|test|db-reset|api-types|eval|bench|replan-bench|gate-selftest>

import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(ROOT, "apps", "web");
const ENGINE = join(ROOT, "services", "engine");
const IS_CI = !!process.env.CI;

const ENV_FILE = join(ROOT, ".env");
const API_TYPES = join(WEB, "src", "lib", "engine-api.ts");

// Create .env from .env.example with a fresh random session secret, if it does not exist yet.
// Runs before setup and gate, so a fresh clone, CI, and the self-test copy all work unattended.
function ensureEnv() {
  if (existsSync(ENV_FILE)) return;
  const example = readFileSync(join(ROOT, ".env.example"), "utf8");
  const secret = randomBytes(32).toString("hex");
  writeFileSync(ENV_FILE, example.replace(/^SESSION_SECRET=.*$/m, `SESSION_SECRET=${secret}`));
  console.log("Created .env from .env.example (with a random SESSION_SECRET)");
}

function loadEnv() {
  ensureEnv();
  // Variables already set in the shell win over .env, so CI or a developer can override one.
  process.loadEnvFile(ENV_FILE);
  // Next.js sends anonymous telemetry by default; a quality gate should not phone home.
  return { ...process.env, NEXT_TELEMETRY_DISABLED: "1" };
}

const ENV = loadEnv();

// A step is one command in one folder. `shell: true` because pnpm and uv are .cmd shims on
// Windows; the folder goes in `cwd` (never in the command string) so spaces in paths are safe.
const step = (name, cwd, command) => ({ name, cwd, command });

const WEB_UNIT = step("web: unit tests", WEB, "pnpm run test");
const ENGINE_UNIT = step("engine: tests", ENGINE, "uv run --locked pytest");

// Order: fastest checks first, so most mistakes fail in seconds.
const GATE = [
  step("secrets: none in git", ROOT, "node scripts/secrets_scan.mjs"),
  step("readme: matches eval/results", ROOT, "node scripts/readme.mjs --check"),
  step("db: start", ROOT, "docker compose up -d --wait"),
  step("api types: up to date", ROOT, "node scripts/tasks.mjs api-types --check"),
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

  // Linux CI runners also need the browser's system libraries.
  const browser = IS_CI && process.platform === "linux" ? "chromium --with-deps" : "chromium";
  return runSteps("setup", [
    step("install web dependencies", ROOT, "pnpm install --frozen-lockfile"),
    step("install engine dependencies", ENGINE, "uv sync --locked"),
    step("install browser for tests", WEB, `pnpm exec playwright install ${browser}`),
    step("start database (waits for health check)", ROOT, "docker compose up -d --wait"),
    step("migrate and seed the dev database", ENGINE, "uv run --locked python -m brimline_engine.db setup"),
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

// The web app's TypeScript types are generated from the engine's OpenAPI schema, so the two
// cannot drift. `--check` fails if the committed file is out of date instead of rewriting it.
function apiTypes(check) {
  const scratch = mkdtempSync(join(tmpdir(), "brimline-api-"));
  try {
    const schema = join(scratch, "openapi.json");
    const generated = join(scratch, "engine-api.ts");
    const dump = spawnSync("uv run --locked python -m brimline_engine.openapi", {
      cwd: ENGINE, env: ENV, shell: true, encoding: "utf8", maxBuffer: 1 << 26,
    });
    if (dump.status !== 0) {
      console.error(dump.stderr);
      return 1;
    }
    writeFileSync(schema, dump.stdout);
    const gen = spawnSync(`pnpm exec openapi-typescript "${schema}" -o "${generated}"`, {
      cwd: WEB, env: ENV, shell: true, stdio: "inherit",
    });
    if (gen.status !== 0) return 1;

    const lf = (text) => text.replace(/\r\n/g, "\n");
    const banner = "// GENERATED from the engine's OpenAPI schema by `make api-types`. Do not edit.\n";
    const fresh = banner + lf(readFileSync(generated, "utf8"));
    const current = existsSync(API_TYPES) ? lf(readFileSync(API_TYPES, "utf8")) : "";
    if (check) {
      if (fresh === current) return 0;
      console.error("✗ apps/web/src/lib/engine-api.ts is out of date. Run `make api-types` and commit it.");
      return 1;
    }
    writeFileSync(API_TYPES, fresh);
    console.log("Wrote apps/web/src/lib/engine-api.ts");
    return 0;
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
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
  "db-reset": () =>
    runSteps("db-reset", [step("reset the dev database", ENGINE, "uv run --locked python -m brimline_engine.db reset")]),
  "api-types": () => apiTypes(process.argv.includes("--check")),
  // Extra arguments pass through, e.g. node scripts/tasks.mjs eval --models claude-haiku-5-5 --split dev
  eval: () =>
    runSteps("eval", [
      step(
        "quote extraction eval",
        ENGINE,
        ["uv run --locked python -m brimline_engine.evals.quote_extract", ...process.argv.slice(3)].join(" "),
      ),
      step("disruption reading eval", ENGINE, "uv run --locked python -m brimline_engine.evals.disruption_parse"),
      step("file checker eval", ENGINE, "uv run --locked python -m brimline_engine.evals.files"),
      step("search eval", ENGINE, "uv run --locked python -m brimline_engine.evals.search"),
      step("quoted-versus-actual flag eval (code only)", ENGINE, "uv run --locked python -m brimline_engine.evals.costing"),
    ]),
  // Extra arguments pass through, e.g. node scripts/tasks.mjs bench --quick
  bench: () =>
    runSteps("bench", [
      step(
        "scheduler benchmark",
        ENGINE,
        ["uv run --locked python -m brimline_engine.scheduling.bench", ...process.argv.slice(3)].join(" "),
      ),
    ]),
  // Re-planning scenarios: lateness versus jobs moved (eval/results/REPLAN.md)
  "replan-bench": () =>
    runSteps("replan-bench", [
      step(
        "re-planning scenarios",
        ENGINE,
        ["uv run --locked python -m brimline_engine.scheduling.replan_bench", ...process.argv.slice(3)].join(" "),
      ),
    ]),
  // The whole app in containers with fake data and prepared replies (M11): http://localhost:3000
  demo: () => {
    const code = runSteps("demo", [step("build and start the app (db, engine, web)", ROOT, "docker compose --profile app up --build -d --wait")]);
    if (code === 0) console.log("\nOpen http://localhost:3000 and sign in as any demo user. Stop with: make demo-stop");
    return code;
  },
  // The engine image as the hosted demo runs it (demo mode, a web key), checked over HTTP: sign in as
  // every role and one write per row-capped table (scripts/demo_smoke.mjs). Also a CI job.
  "demo-smoke": () => {
    const compose = "docker compose -f docker-compose.yml -f docker-compose.smoke.yml --profile app";
    const env = { ...ENV, SMOKE_ENGINE_KEY: randomBytes(24).toString("hex") };
    const run = (cmd) => spawnSync(cmd, { cwd: ROOT, env, shell: true, stdio: "inherit" }).status ?? 1;
    let code = run(`${compose} up --build -d --wait engine`);
    if (code === 0) code = run(`node "${join(ROOT, "scripts", "demo_smoke.mjs")}"`);
    if (code !== 0) run(`${compose} logs --tail 60 engine`);
    run(`${compose} stop engine`);
    return code;
  },
  "demo-stop": () => runSteps("demo-stop", [step("stop the app containers", ROOT, "docker compose --profile app stop engine web")]),
  screenshots: () => spawnSync(`node "${join(ROOT, "scripts", "showcase.mjs")}" screenshots`, { cwd: ROOT, env: ENV, shell: true, stdio: "inherit" }).status ?? 1,
  // Extra arguments pass through: node scripts/tasks.mjs demo-video --record
  "demo-video": () =>
    spawnSync(`node "${join(ROOT, "scripts", "showcase.mjs")}" video ${process.argv.slice(3).join(" ")}`, { cwd: ROOT, env: ENV, shell: true, stdio: "inherit" })
      .status ?? 1,
  readme: () => runSteps("readme", [step("write README tables from eval/results", ROOT, "node scripts/readme.mjs")]),
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
