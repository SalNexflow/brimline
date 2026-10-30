#!/usr/bin/env node
// Proves the gate is not a rubber stamp. It plants one deliberate error at a time and requires the
// gate to fail *at the step meant to catch it*.
//
// Safety: it never edits your working tree. It refuses to run on a dirty tree (uncommitted changes
// would not be in the copy, so the result would describe code you are not looking at), exports the
// last commit into a throwaway folder (.selftest/, git-ignored), and deletes that folder afterwards.
//
// Usage: node scripts/gate_selftest.mjs [--keep]   (--keep leaves the copy for inspection)

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SCRATCH = join(ROOT, ".selftest");
const COPY = join(SCRATCH, "repo");
const RESULT_FILE = join(SCRATCH, "gate-result.json");
const KEEP = process.argv.includes("--keep");

// Each mutation changes `find` to `replace` in one file. `expect` is the gate step that must fail.
// Most break *code* and let an existing test catch it, which is the realistic case.
const MUTATIONS = [
  {
    name: "TypeScript type error",
    file: "apps/web/src/app/page.tsx",
    find: "export default function HomePage() {",
    replace: 'const shopName: number = "Brimline";\nexport default function HomePage() {\n  void shopName;',
    expect: "web: typecheck",
  },
  {
    name: "ESLint violation (unused variable)",
    file: "apps/web/src/app/page.tsx",
    find: "export default function HomePage() {",
    replace: "const unusedValue = 42;\nexport default function HomePage() {",
    expect: "web: lint",
  },
  {
    name: "web behaviour change caught by a unit test",
    file: "apps/web/src/app/page.tsx",
    find: "All data is\n        synthetic.",
    replace: "All data is\n        real.",
    expect: "web: unit tests",
  },
  {
    name: "Python lint violation (unused import)",
    file: "services/engine/src/brimline_engine/main.py",
    find: "from typing import Literal",
    replace: "import os\nfrom typing import Literal",
    expect: "engine: lint",
  },
  {
    name: "Python formatting drift",
    file: "services/engine/src/brimline_engine/main.py",
    find: 'app = FastAPI(title="Brimline engine", version="0.0.0", lifespan=lifespan)',
    replace: 'app = FastAPI( title = "Brimline engine",version="0.0.0",lifespan=lifespan )',
    expect: "engine: format",
  },
  {
    name: "Python type error",
    file: "services/engine/src/brimline_engine/main.py",
    find: '    return Health(status="ok", service="engine")',
    replace: '    return Health(status="ok", service="engine")\n\n\ndef broken() -> int:\n    return "not an int"',
    expect: "engine: typecheck",
  },
  {
    // Renaming a route changes the OpenAPI schema, so the web's generated types go stale first.
    name: "engine route renamed without regenerating web types",
    file: "services/engine/src/brimline_engine/main.py",
    find: '@app.get("/health")',
    replace: '@app.get("/healthz")',
    expect: "api types: up to date",
  },
  {
    // A permission widening changes no types at all; only the hand-written permission table sees it.
    name: "permission widened (operators may create orders)",
    file: "services/engine/src/brimline_engine/permissions.py",
    // The operator's set (the only one listing task.update right after queue.read and before file.read).
    find: '            "queue.read",\n            "task.update",\n            "file.read",',
    // Swapped rather than added, so the formatting stays the same and only the tests can catch it.
    replace: '            "queue.read",\n            "task.update",\n            "order.create",',
    expect: "engine: tests",
  },
  {
    // An off-by-one-cent rounding change: only the hand-worked pricing tests notice.
    name: "pricing rounds the rush surcharge wrongly",
    file: "services/engine/src/brimline_engine/pricing.py",
    find: "return (subtotal_cents * percent + 50) // 100",
    replace: "return (subtotal_cents * percent + 49) // 100",
    expect: "engine: tests",
  },
  {
    name: "page change only a browser test sees (title)",
    file: "apps/web/src/app/layout.tsx",
    find: '  title: "Brimline",',
    replace: '  title: "Untitled",',
    expect: "web: browser tests",
  },
  {
    name: "checker lets a changeover one minute short through",
    file: "services/engine/src/brimline_engine/checker/check.py",
    find: "and nxt.start - prev.end < r.changeover",
    replace: "and nxt.start - prev.end < r.changeover - 1",
    expect: "engine: tests",
  },
  {
    name: "checker imports scheduler code",
    file: "services/engine/src/brimline_engine/checker/check.py",
    find: "from brimline_engine.checker.rules import Rules, durations",
    replace:
      "from brimline_engine.checker.rules import Rules, durations\nfrom brimline_engine.scheduling.model import TASK_ORDER as _UNUSED  # noqa: F401",
    expect: "engine: tests",
  },
  {
    name: "approval no longer re-runs the independent checker",
    file: "services/engine/src/brimline_engine/planning/schedules.py",
    find: "        if not result.valid:",
    replace: "        if result.valid is None:",
    expect: "engine: tests",
  },
  {
    name: "AI summary no longer checked against the diff",
    file: "services/engine/src/brimline_engine/planning/replan.py",
    find: "known_ids = set(IDENTIFIER.findall(diff_text))",
    replace: "known_ids = set(IDENTIFIER.findall(text))",
    expect: "engine: tests",
  },
  {
    // M7: a hole in the mesh is no longer seen, so a broken file would pass (a false pass).
    name: "file checker stops counting open edges",
    file: "services/engine/src/brimline_engine/files/measure.py",
    find: "        boundary=int((u_counts == 1).sum()),",
    replace: "        boundary=0,",
    expect: "engine: tests",
  },
  {
    // M8: the first lock (the customer's filter is rewritten to their own customer) is skipped.
    name: "search no longer narrows a customer's filter",
    file: "services/engine/src/brimline_engine/search/query.py",
    find: "    if _scope_of(actor) is None:\n        return Scoped(filter=f, notices=[])",
    replace: "    if True:\n        return Scoped(filter=f, notices=[])",
    expect: "engine: tests",
  },
  {
    // M8: the second lock (the SQL itself is scoped) is removed.
    name: "search SQL loses its customer scope",
    file: "services/engine/src/brimline_engine/search/query.py",
    find: '    " WHERE (%(scope)s::bigint IS NULL OR o.customer_id = %(scope)s::bigint)"',
    replace: '    " WHERE (%(scope)s::bigint IS NULL OR TRUE)"',
    expect: "engine: tests",
  },
  {
    // M11: the hosted engine would answer anyone, not only the web app.
    name: "engine stops checking the web key",
    file: "services/engine/src/brimline_engine/main.py",
    find: '        if request.url.path != "/health" and not hmac.compare_digest(',
    // Still valid code (lint passes): the key is now checked only on a path nobody calls.
    replace: '        if request.url.path == "/nowhere" and not hmac.compare_digest(',
    expect: "engine: tests",
  },
  {
    // M11: the hosted demo would keep calling the model after its daily budget is spent.
    name: "demo ignores its daily model budget",
    file: "services/engine/src/brimline_engine/ai/guard.py",
    find: "    if s.today_usd >= budget.daily_usd:",
    replace: "    if False:",
    expect: "engine: tests",
  },
  {
    // M10: a type exactly at the threshold would count as over.
    name: "under-quote flag counts a job at the threshold as over",
    file: "services/engine/src/brimline_engine/costing/report.py",
    find: "return row.actual_cents * threshold.denominator > row.estimated_cents * threshold.numerator",
    replace: "return row.actual_cents * threshold.denominator >= row.estimated_cents * threshold.numerator",
    expect: "engine: tests",
  },
  {
    // M10: a type could be flagged from too few jobs.
    name: "under-quote flag ignores the minimum number of jobs",
    file: "services/engine/src/brimline_engine/costing/report.py",
    find: "flagged = n >= rule.min_jobs and p is not None",
    replace: "flagged = n >= 0 and p is not None",
    expect: "engine: tests",
  },
  {
    // M10: reprints would look free, hiding what failures cost the shop.
    name: "failed attempts left out of the actual cost",
    file: "services/engine/src/brimline_engine/costing/outcome.py",
    find: "    for a in attempts:\n        used =",
    replace: "    for a in (x for x in attempts if not x.failed):\n        used =",
    expect: "engine: tests",
  },
  {
    name: "a failed file check can be accepted like a warning",
    file: "services/engine/src/brimline_engine/files/service.py",
    find: '        if check.status != "warn":',
    replace: '        if check.status not in ("warn", "fail"):',
    expect: "engine: tests",
  },
];

function sh(command, cwd, extraEnv = {}) {
  return spawnSync(command, { cwd, shell: true, stdio: "inherit", env: { ...process.env, ...extraEnv } }).status;
}

function capture(command, cwd) {
  return spawnSync(command, { cwd, shell: true, encoding: "utf8" }).stdout ?? "";
}

function runGate() {
  rmSync(RESULT_FILE, { force: true });
  const status = sh("node scripts/tasks.mjs gate", COPY, { GATE_RESULT_FILE: RESULT_FILE });
  const failedStep = existsSync(RESULT_FILE) ? JSON.parse(readFileSync(RESULT_FILE, "utf8")).failedStep : "unknown";
  return { status, failedStep };
}

function main() {
  if (capture("git status --porcelain", ROOT).trim() !== "") {
    console.error("✗ Refusing to run: the git tree has uncommitted changes. Commit or stash them first.");
    return 1;
  }

  // Fresh copy of the last commit. `git archive` exports tracked files only (no .git, no secrets).
  rmSync(SCRATCH, { recursive: true, force: true });
  mkdirSync(COPY, { recursive: true });
  // Relative tar path: GNU tar would read "C:\..." as a remote host.
  if (sh("git archive --format=tar -o .selftest/head.tar HEAD", ROOT) !== 0) return 1;
  if (sh("tar -xf ../head.tar", COPY) !== 0) return 1;

  console.log("\n=== Installing dependencies in the throwaway copy");
  if (sh("pnpm install --frozen-lockfile --prefer-offline", COPY) !== 0) return 1;
  if (sh("uv sync --locked", join(COPY, "services", "engine")) !== 0) return 1;

  // Without a green baseline, every mutation would look "caught" for the wrong reason.
  console.log("\n=== Baseline: the unmodified copy must pass the gate");
  const baseline = runGate();
  if (baseline.status !== 0) {
    console.error(`✗ Baseline gate failed at '${baseline.failedStep}'. Fix the gate before trusting the self-test.`);
    return 1;
  }

  const results = [];
  for (const m of MUTATIONS) {
    const path = join(COPY, m.file);
    const original = readFileSync(path, "utf8");
    if (!original.includes(m.find)) {
      // The code moved on; fail loudly instead of silently testing nothing.
      results.push({ ...m, caught: false, note: `anchor text not found in ${m.file}; update the mutation` });
      continue;
    }
    console.log(`\n=== Mutation: ${m.name}  (expect '${m.expect}' to fail)`);
    writeFileSync(path, original.replace(m.find, m.replace));
    const { status, failedStep } = runGate();
    writeFileSync(path, original);
    const caught = status !== 0 && failedStep === m.expect;
    results.push({ ...m, caught, note: status === 0 ? "gate stayed GREEN" : `failed at '${failedStep}'` });
  }

  console.log("\nGate self-test results");
  for (const r of results) console.log(`  ${r.caught ? "CAUGHT" : "MISSED"}  ${r.name}: ${r.note}`);
  const missed = results.filter((r) => !r.caught).length;
  console.log(missed ? `\n✗ ${missed} of ${results.length} mutations not caught as expected` : `\n✓ all ${results.length} mutations caught at the expected step`);
  return missed ? 1 : 0;
}

let code = 1;
try {
  code = main();
} finally {
  if (!KEEP) rmSync(SCRATCH, { recursive: true, force: true });
}
process.exit(code);
