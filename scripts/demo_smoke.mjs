#!/usr/bin/env node
// Smoke test of the engine as the hosted demo runs it: the Docker image, demo mode on, a web key,
// a real Postgres with the non-superuser roles. Found by deploying: every hosted sign-in failed
// on a row cap that only demo mode checks (DEFECT_LOG #81), which no unit test reached.
//
// It signs in as every demo user and makes one write that passes each row-capped table's check
// (the list must match config/demo.toml, so a new cap without a write here fails).
//
// Usage: node scripts/tasks.mjs demo-smoke   (starts the engine, runs this, stops it)
//        SMOKE_ENGINE_URL=... SMOKE_ENGINE_KEY=... node scripts/demo_smoke.mjs

import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.SMOKE_ENGINE_URL ?? "http://localhost:8000";
const KEY = process.env.SMOKE_ENGINE_KEY ?? "";

const failures = [];
function check(ok, what) {
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${what}`);
  if (!ok) failures.push(what);
}

async function call(method, path, { token, body, raw, key = KEY } = {}) {
  const headers = { "X-Engine-Key": key };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (method !== "GET") headers["Idempotency-Key"] = randomUUID();
  if (raw) headers["Content-Type"] = "application/octet-stream";
  else if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(BASE + path, { method, headers, body: raw ?? (body === undefined ? undefined : JSON.stringify(body)) });
  const text = await r.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    // not JSON (a 500 page): kept as text for the message
  }
  return { status: r.status, json, text: text.slice(0, 200) };
}

/** The table names under [storage.max_rows] in config/demo.toml. */
function cappedTables() {
  const toml = readFileSync(join(ROOT, "config", "demo.toml"), "utf8");
  const section = toml.split("[storage.max_rows]")[1]?.split(/^\[/m)[0] ?? "";
  return [...section.matchAll(/^([a-z_]+)\s*=/gm)].map((m) => m[1]).sort();
}

function inDays(n) {
  return new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);
}

// One write per capped table: [table, role that may do it, the write]. Each returns a response.
const WRITES = [
  ["orders", "staff", (t) =>
    call("POST", "/orders", { token: t, body: {
      customer_code: "C-HARBOR", due_date: inDays(21), rush: false, notes: "smoke test",
      lines: [{ part_name: "Bracket", quantity: 1, material_code: "PLA-BLACK" }],
    } })],
  ["quote_requests", "staff", (t) =>
    call("POST", "/quote-requests", { token: t, body: { customer_code: "C-HARBOR", message: "10 phone stands in black PLA" } })],
  ["files", "staff", async (t, ctx) =>
    call("POST", `/files?quote=${ctx.quote}&line=1&filename=cube.stl`, {
      token: t, raw: readFileSync(join(ROOT, "eval", "datasets", "files", "blind", "models", "b01.stl")),
    })],
  ["ai_calls", "staff", (t) => call("POST", "/search", { token: t, body: { question: "jobs due this week not printed yet" } })],
  ["disruptions", "planner", (t) => call("POST", "/disruptions", { token: t, body: { message: "Printer 1 jammed for 4 hours" } })],
  ["planning_runs", "planner", (t) => call("POST", "/planning-runs", { token: t })],
];

async function main() {
  console.log(`Demo smoke test against ${BASE}`);
  check((await call("GET", "/health", { key: "" })).status === 200, "health answers without the key");
  check((await call("GET", "/auth/demo-users", { key: "" })).status === 401, "anything else without the key is refused");
  const status = await call("GET", "/demo-status");
  check(status.json?.demo_mode === true, "demo mode is on");

  const users = (await call("GET", "/auth/demo-users")).json ?? [];
  check(users.length > 0, `demo users listed (${users.length})`);
  const tokens = {};
  for (const u of users) {
    const login = await call("POST", "/auth/demo-login", { body: { user_code: u.code } });
    const me = login.json?.token ? await call("GET", "/me", { token: login.json.token }) : null;
    check(login.status === 200 && me?.json?.role === u.role, `sign in as ${u.code} (${u.role}): ${login.status}${login.status === 200 ? "" : ` ${login.text}`}`);
    if (login.json?.token) tokens[u.role] ??= login.json.token;
  }

  const ctx = {};
  for (const [table, role, write] of WRITES) {
    const r = await write(tokens[role], ctx);
    if (table === "quote_requests") ctx.quote = r.json?.quote_number;
    check(r.status >= 200 && r.status < 300, `a write into ${table} as ${role}: ${r.status}${r.status < 300 ? "" : ` ${r.text}`}`);
    if (table === "disruptions") {
      // The demo's example phrase must resolve at any hour (DEFECT_LOG #81 follow-up).
      check(!JSON.stringify(r.json ?? "").includes("cannot read the time"), "the example disruption's time is understood");
    }
  }
  const covered = WRITES.map(([t]) => t).sort();
  check(JSON.stringify(covered) === JSON.stringify(cappedTables()), `every row-capped table in config/demo.toml has a write here (${cappedTables().join(", ")})`);

  console.log(failures.length ? `\n✗ ${failures.length} smoke check(s) failed` : "\n✓ demo smoke test passed");
  return failures.length ? 1 : 0;
}

process.exit(await main());
